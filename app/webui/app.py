"""
CogAgent Client Web UI - Flask Version
基于 Flask + HTML/CSS/JS 的客户端，替代 Gradio 版本的 client.py
功能与原 client.py 完全一致

服务端运行：python app/openai_demo.py --model_path THUDM/cogagent-9b-20241220 --host 0.0.0.0 --port 7870
客户端运行：python app/webui/app.py --api_key EMPTY --base_url http://127.0.0.1:7870/v1 --host 127.0.0.1 --port 7860 --platform WIN
"""

import argparse
import base64
import platform
import pyautogui
import re
import os
import json
import threading
import time
import uuid
from PIL import Image, ImageDraw
from typing import List, Dict, Any, Optional, Tuple
from flask import Flask, render_template, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename

# 导入操作执行模块
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from register import agent

app = Flask(__name__)
CORS(app)

# 全局变量
stop_event = threading.Event()
current_session = {}

# 配置
CACHE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'caches')
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}

app.config['CACHE_FOLDER'] = CACHE_FOLDER
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# API 配置（从命令行参数获取）
api_config = {
    'api_key': 'EMPTY',
    'base_url': 'http://127.0.0.1:7870/v1',
    'model': 'CogAgent',
    'platform': 'WIN'
}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def identify_os() -> str:
    """识别操作系统"""
    os_detail = platform.platform().lower()
    if "mac" in os_detail:
        return "Mac"
    elif "windows" in os_detail:
        return "WIN"
    else:
        return "WIN"


def encode_image(image_path: str) -> str:
    """将图片编码为base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def create_chat_completion(
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Dict[str, Any]],
    max_length: int = 512,
    top_p: float = 1.0,
    temperature: float = 1.0,
    presence_penalty: float = 1.0,
) -> Any:
    """调用OpenAI兼容API - 与原client.py完全一致"""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=False,
        timeout=60,
        max_tokens=max_length,
        temperature=temperature,
        presence_penalty=presence_penalty,
        top_p=top_p,
    )
    if response:
        return response.choices[0].message.content
    return None


def shot_current_screen(round_num: int) -> str:
    """截取当前屏幕 - 与原client.py完全一致"""
    img = pyautogui.screenshot()
    filepath = os.path.join(CACHE_FOLDER, f"img_{round_num}.png")
    img.save(filepath)
    return filepath


def formatting_input(
    task: str, 
    history_step: List[str], 
    history_action: List[str], 
    round_num: int
) -> List[Dict[str, Any]]:
    """格式化输入消息 - 与原client.py完全一致"""
    current_platform = api_config['platform']
    platform_str = f"(Platform: {current_platform})\n"
    format_str = "(Answer in Status-Plan-Action-Operation-Sensitive format.)\n"

    if len(history_step) != len(history_action):
        raise ValueError("Mismatch in lengths of history_step and history_action.")

    history_str = "\nHistory steps: "
    for index, (step, action) in enumerate(zip(history_step, history_action)):
        history_str += f"\n{index}. {step}\t{action}"

    query = f"Task: {task}{history_str}\n{platform_str}{format_str}"

    # Create image URL with base64 encoding
    img_path = os.path.join(CACHE_FOLDER, f"img_{round_num}.png")
    img_url = f"data:image/jpeg;base64,{encode_image(img_path)}"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": query},
                {"type": "image_url", "image_url": {"url": img_url}},
            ],
        },
    ]
    return messages


def extract_grounded_operation(response: str) -> Tuple[Optional[str], Optional[str]]:
    """从响应中提取操作 - 与原client.py完全一致"""
    grounded_pattern = r"Grounded Operation:\s*(.*)"
    action_pattern = r"Action:\s*(.*)"

    step = None
    action = None

    matches_history = re.search(grounded_pattern, response)
    matches_actions = re.search(action_pattern, response)
    if matches_history:
        step = matches_history.group(1)
    if matches_actions:
        action = matches_actions.group(1)

    return step, action


def draw_boxes_on_image(image: Image.Image, boxes: List[List[float]], save_path: str):
    """在图片上绘制边界框 - 与原client.py完全一致"""
    draw = ImageDraw.Draw(image)
    for box in boxes:
        x_min = int(box[0] * image.width)
        y_min = int(box[1] * image.height)
        x_max = int(box[2] * image.width)
        y_max = int(box[3] * image.height)
        draw.rectangle([x_min, y_min, x_max, y_max], outline="red", width=3)
    image.save(save_path)


def extract_bboxes(response: str, round_num: int) -> Optional[str]:
    """提取边界框并绘制 - 与原client.py完全一致"""
    box_pattern = r"box=\[\[?(\d+),(\d+),(\d+),(\d+)\]?\]"
    matches = re.findall(box_pattern, response)
    if matches:
        boxes = [[int(x) / 1000 for x in match] for match in matches]
        img_save_path = os.path.join(CACHE_FOLDER, f"img_{round_num}_bbox.png")
        img_path = os.path.join(CACHE_FOLDER, f"img_{round_num}.png")
        image = Image.open(img_path).convert("RGB")
        draw_boxes_on_image(image, boxes, img_save_path)
        return f"img_{round_num}_bbox.png"
    return None


def is_balanced(s: str) -> bool:
    """检查括号是否平衡 - 与原client.py完全一致"""
    stack = []
    mapping = {")": "(", "]": "[", "}": "{"}
    if "(" not in s:
        return False
    for char in s:
        if char in mapping.values():
            stack.append(char)
        elif char in mapping.keys():
            if not stack or mapping[char] != stack.pop():
                return False
    return not stack


def extract_operation(step: Optional[str]) -> Dict[str, Any]:
    """提取操作详情 - 与原client.py完全一致"""
    if step is None or not is_balanced(step):
        return {"operation": "NO_ACTION"}

    op, detail = step.split("(", 1)
    detail = "(" + detail
    others_pattern = r"(\w+)\s*=\s*([^,)]+)"
    others = re.findall(others_pattern, detail)
    Grounded_Operation = dict(others)

    boxes_pattern = r"box=\[\[(.*?)\]\]"
    boxes = re.findall(boxes_pattern, detail)
    if boxes:
        Grounded_Operation["box"] = list(map(int, boxes[0].split(",")))
    Grounded_Operation["operation"] = op.strip()

    return Grounded_Operation


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/caches/<filename>')
def cached_file(filename):
    """获取缓存文件"""
    return send_from_directory(CACHE_FOLDER, filename)


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """获取上传的文件"""
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/upload', methods=['POST'])
def upload_file():
    """上传图片 - 与inference/webui一致"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(filepath)
        return jsonify({'filename': unique_filename, 'path': filepath})
    
    return jsonify({'error': 'Invalid file type'}), 400


@app.route('/workflow', methods=['POST'])
def workflow():
    """
    主工作流 - 与原client.py的workflow函数完全一致
    自动截图、调用模型、执行操作的循环
    """
    global current_session
    
    data = request.json
    session_id = data.get('session_id', str(uuid.uuid4()))
    task = data.get('task', '')
    
    # 使用默认参数值（与原client.py一致）
    max_length = 4096
    top_p = 0.8
    temperature = 0.6
    
    # 重置停止事件
    stop_event.clear()
    
    def generate():
        history_step = []
        history_action = []
        round_num = 1
        
        try:
            # 发送开始警告
            yield f"data: {json.dumps({'type': 'warning_start'})}\n\n"
            
            while True:
                print(f"\033[92m Round {round_num}: \033[0m")
                
                if round_num > 15:
                    break  # Exit the loop after 15 rounds
                
                # 发送轮次信息
                yield f"data: {json.dumps({'type': 'round', 'round': round_num})}\n\n"
                
                # 截取当前屏幕
                shot_current_screen(round_num)
                
                # 格式化输入消息
                messages = formatting_input(task, history_step, history_action, round_num)
                
                # 调用API获取响应
                response = create_chat_completion(
                    api_key=api_config['api_key'],
                    base_url=api_config['base_url'],
                    model=api_config['model'],
                    messages=messages,
                    max_length=max_length,
                    top_p=top_p,
                    temperature=temperature,
                )
                
                if not response:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Model returned empty response'})}\n\n"
                    break
                
                # 发送模型响应
                yield f"data: {json.dumps({'type': 'response', 'content': response})}\n\n"
                
                # 提取操作
                step, action = extract_grounded_operation(response)
                history_step.append(step if step else "")
                history_action.append(action if action else "")
                
                # 处理边界框
                bbox_filename = extract_bboxes(response, round_num)
                
                # 提取操作详情
                grounded_operation = extract_operation(step)
                
                if grounded_operation["operation"] == "NO_ACTION":
                    break
                
                # 执行操作
                status = agent(grounded_operation)
                
                # 发送图片路径
                if bbox_filename:
                    output_image = f"/caches/{bbox_filename}"
                    yield f"data: {json.dumps({'type': 'image', 'path': output_image})}\n\n"
                
                # 检查是否结束或停止
                if status == "END" or stop_event.is_set():
                    if bbox_filename and round_num > 1:
                        prev_bbox = f"/caches/img_{round_num - 1}_bbox.png"
                        yield f"data: {json.dumps({'type': 'image', 'path': prev_bbox})}\n\n"
                    
                    if stop_event.is_set():
                        yield f"data: {json.dumps({'type': 'stopped'})}\n\n"
                    break
                
                round_num += 1
            
            # 发送结束警告
            yield f"data: {json.dumps({'type': 'warning_end'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # 清除停止事件
            stop_event.clear()
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/stop', methods=['POST'])
def stop_execution():
    """停止执行 - 与原client.py的switch函数一致"""
    stop_event.set()
    return jsonify({'status': 'stopped'})


@app.route('/clear', methods=['POST'])
def clear_session():
    """清空会话 - 与原client.py的clear_button功能一致"""
    data = request.json
    session_id = data.get('session_id')
    
    if session_id in current_session:
        del current_session[session_id]
    
    return jsonify({'status': 'success'})


def main():
    parser = argparse.ArgumentParser(description="CogAgent Client Web UI")
    parser.add_argument("--api_key", default="EMPTY", help="OpenAI API Key")
    parser.add_argument("--base_url", default="http://127.0.0.1:7870/v1", help="OpenAI API Base URL")
    parser.add_argument("--model", default="CogAgent", help="Model name")
    parser.add_argument("--host", default="127.0.0.1", help="Host IP for the server")
    parser.add_argument("--port", type=int, default=7860, help="Port for the server")
    parser.add_argument("--platform", default=None, help="Platform (WIN/Mac/Mobile)")
    
    args = parser.parse_args()
    
    # 更新API配置
    api_config['api_key'] = args.api_key
    api_config['base_url'] = args.base_url
    api_config['model'] = args.model
    api_config['platform'] = args.platform if args.platform else identify_os()
    
    # 确保目录存在
    os.makedirs(CACHE_FOLDER, exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    print(f"="*50)
    print(f"CogAgent Client Web UI")
    print(f"="*50)
    print(f"API Base URL: {api_config['base_url']}")
    print(f"Model: {api_config['model']}")
    print(f"Platform: {api_config['platform']}")
    print(f"="*50)
    print(f"Starting server at http://{args.host}:{args.port}")
    print(f"="*50)
    
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
