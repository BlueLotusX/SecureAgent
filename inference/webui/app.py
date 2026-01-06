import argparse
import os
import re
import torch
import base64
import json
from threading import Thread, Event
from PIL import Image, ImageDraw
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TextIteratorStreamer,
)
from typing import List
from werkzeug.utils import secure_filename
import uuid
from io import BytesIO

app = Flask(__name__)
CORS(app)

# 全局变量
tokenizer = None
model = None
platform_str = ""
format_str = ""
output_dir = ""
stop_event = Event()
current_session = {}

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def draw_boxes_on_image(image: Image.Image, boxes: List[List[float]], save_path: str):
    """绘制边界框"""
    draw = ImageDraw.Draw(image)
    for box in boxes:
        x_min = int(box[0] * image.width)
        y_min = int(box[1] * image.height)
        x_max = int(box[2] * image.width)
        y_max = int(box[3] * image.height)
        draw.rectangle([x_min, y_min, x_max, y_max], outline="red", width=3)
    image.save(save_path)


def preprocess_messages(history, img_path):
    """预处理消息历史"""
    history_step = []
    for task, model_msg in history:
        grounded_pattern = r"Grounded Operation:\s*(.*)"
        matches_history = re.search(grounded_pattern, model_msg)
        if matches_history:
            grounded_operation = matches_history.group(1)
            history_step.append(grounded_operation)

    history_str = "\nHistory steps: "
    if history_step:
        for i, step in enumerate(history_step):
            history_str += f"\n{i}. {step}"

    if history:
        task = history[-1][0]
    else:
        task = "No task provided"

    query = f"Task: {task}{history_str}\n{platform_str}{format_str}"
    image = Image.open(img_path).convert("RGB")
    return query, image


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    """上传图片"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        print(f"File saved to: {filepath}")
        print(f"File exists: {os.path.exists(filepath)}")
        return jsonify({'filename': unique_filename, 'path': filepath})
    
    return jsonify({'error': 'Invalid file type'}), 400


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """获取上传的文件"""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    print(f"Requesting file: {filepath}")
    print(f"File exists: {os.path.exists(filepath)}")
    print(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/results/<filename>')
def result_file(filename):
    """获取结果文件"""
    result_dir = output_dir if output_dir else 'results'
    # 转换为绝对路径
    if not os.path.isabs(result_dir):
        result_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), result_dir)
    
    filepath = os.path.join(result_dir, filename)
    print(f"Requesting result file: {filepath}")
    print(f"Result file exists: {os.path.exists(filepath)}")
    print(f"Result directory: {result_dir}")
    
    return send_from_directory(result_dir, filename)


@app.route('/predict', methods=['POST'])
def predict():
    """预测接口 - 流式返回"""
    global current_session
    
    data = request.json
    session_id = data.get('session_id', str(uuid.uuid4()))
    task = data.get('task', '')
    img_path = data.get('img_path', '')
    max_length = data.get('max_length', 1024)
    
    if not img_path or not os.path.exists(img_path):
        return jsonify({'error': 'Image not found'}), 400
    
    # 初始化或获取会话
    if session_id not in current_session:
        current_session[session_id] = {'history': []}
    
    history = current_session[session_id]['history']
    history.append([task, ""])
    
    # 重置停止事件
    stop_event.clear()
    
    def generate():
        try:
            query, image = preprocess_messages(history, img_path)
            inputs = tokenizer.apply_chat_template(
                [{"role": "user", "image": image, "content": query}],
                add_generation_prompt=True,
                tokenize=True,
                return_tensors="pt",
                return_dict=True,
            ).to(model.device)
            
            streamer = TextIteratorStreamer(
                tokenizer, timeout=60, skip_prompt=True, skip_special_tokens=True
            )
            
            generate_kwargs = {
                "input_ids": inputs["input_ids"],
                "attention_mask": inputs["attention_mask"],
                "position_ids": inputs["position_ids"],
                "images": inputs["images"],
                "streamer": streamer,
                "max_length": max_length,
                "do_sample": True,
                "top_k": 1,
            }
            
            t = Thread(target=model.generate, kwargs=generate_kwargs)
            t.start()
            
            with torch.no_grad():
                for new_token in streamer:
                    if stop_event.is_set():
                        yield f"data: {json.dumps({'type': 'stopped'})}\n\n"
                        return
                    
                    if new_token:
                        history[-1][1] += new_token
                        yield f"data: {json.dumps({'type': 'token', 'content': new_token})}\n\n"
            
            # 检查是否有边界框
            response = history[-1][1]
            box_pattern = r"box=\[\[?(\d+),(\d+),(\d+),(\d+)\]?\]"
            matches = re.findall(box_pattern, response)
            
            if matches:
                boxes = [[int(x) / 1000 for x in match] for match in matches]
                os.makedirs(output_dir, exist_ok=True)
                base_name = os.path.splitext(os.path.basename(img_path))[0]
                round_num = len([h for h in history if h[0] and h[1]])
                output_filename = f"{base_name}_{round_num}.png"
                output_path = os.path.join(output_dir, output_filename)
                image = Image.open(img_path).convert("RGB")
                draw_boxes_on_image(image, boxes, output_path)
                yield f"data: {json.dumps({'type': 'image', 'path': f'/results/{output_filename}'})}\n\n"
            
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return app.response_class(generate(), mimetype='text/event-stream')


@app.route('/stop', methods=['POST'])
def stop_generation():
    """停止生成"""
    stop_event.set()
    return jsonify({'status': 'stopped'})


@app.route('/undo', methods=['POST'])
def undo_last():
    """撤销最后一轮"""
    data = request.json
    session_id = data.get('session_id')
    
    if session_id in current_session and current_session[session_id]['history']:
        current_session[session_id]['history'].pop()
        return jsonify({'status': 'success', 'history': current_session[session_id]['history']})
    
    return jsonify({'status': 'success', 'history': []})


@app.route('/clear', methods=['POST'])
def clear_history():
    """清空历史"""
    data = request.json
    session_id = data.get('session_id')
    
    if session_id in current_session:
        current_session[session_id]['history'] = []
    
    return jsonify({'status': 'success'})


@app.route('/history', methods=['GET'])
def get_history():
    """获取历史记录"""
    session_id = request.args.get('session_id')
    
    if session_id in current_session:
        return jsonify({'history': current_session[session_id]['history']})
    
    return jsonify({'history': []})


def main():
    parser = argparse.ArgumentParser(description="CogAgent Flask Demo")
    parser.add_argument("--host", default="127.0.0.1", help="Host IP for the server.")
    parser.add_argument("--port", type=int, default=7860, help="Port for the server.")
    parser.add_argument("--model_dir", required=True, help="Path or identifier of the model.")
    parser.add_argument("--format_key", default="action_op_sensitive", help="Key to select the prompt format.")
    parser.add_argument("--platform", default="Mac", help="Platform information string.")
    parser.add_argument("--output_dir", default="results", help="Directory to save annotated images.")
    args = parser.parse_args()

    format_dict = {
        "action_op_sensitive": "(Answer in Action-Operation-Sensitive format.)",
        "status_plan_action_op": "(Answer in Status-Plan-Action-Operation format.)",
        "status_action_op_sensitive": "(Answer in Status-Action-Operation-Sensitive format.)",
        "status_action_op": "(Answer in Status-Action-Operation format.)",
        "action_op": "(Answer in Action-Operation format.)"
    }

    if args.format_key not in format_dict:
        raise ValueError(f"Invalid format_key. Available keys: {list(format_dict.keys())}")

    global tokenizer, model, platform_str, format_str, output_dir
    
    print("Loading model...")
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model_dir, torch_dtype=torch.bfloat16, trust_remote_code=True, device_map="auto"
    ).eval()
    print("Model loaded successfully!")

    platform_str = f"(Platform: {args.platform})\n"
    format_str = format_dict[args.format_key]
    
    # 转换 output_dir 为绝对路径
    if not os.path.isabs(args.output_dir):
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output_dir)
    else:
        output_dir = args.output_dir
    
    # 确保目录存在
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Upload folder: {UPLOAD_FOLDER}")
    print(f"Output folder: {output_dir}")
    print(f"Starting server at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

