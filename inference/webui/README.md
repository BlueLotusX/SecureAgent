# SecureAgentPolyU Web UI

基于 Flask + 纯 HTML/CSS/JavaScript 的 CogAgent Web 界面，完全自定义样式，不依赖 Gradio。

## 特性

- ✅ 完全自定义的样式，不受第三方框架限制
- ✅ 流式响应输出
- ✅ 图片上传（支持拖拽）
- ✅ 聊天历史记录
- ✅ 实时停止生成
- ✅ 撤销和清空历史
- ✅ 标注图片显示和下载
- ✅ 响应式设计，支持移动端

## 安装依赖

```bash
pip install flask flask-cors torch transformers Pillow
```

或使用 requirements.txt：

```bash
pip install -r inference/webui/requirements.txt
```

## 运行命令

```bash
python inference/webui/app.py --host 127.0.0.1 --port 7860 --model_dir THUDM/cogagent-9b-20241220 --format_key status_action_op_sensitive --platform "WIN" --output_dir ./results
```

### 参数说明

- `--host`: 服务器地址（默认：127.0.0.1）
- `--port`: 端口号（默认：7860）
- `--model_dir`: 模型路径或 HuggingFace 模型 ID（必需）
- `--format_key`: 输出格式（默认：action_op_sensitive）
- `--platform`: 平台信息（默认：Mac）
- `--output_dir`: 标注图片保存目录（默认：results）

## 访问

启动后访问：http://127.0.0.1:7860

## 文件结构

```
inference/webui/
├── app.py              # Flask 后端服务器
├── requirements.txt    # Python 依赖
├── README.md          # 说明文档
├── templates/
│   └── index.html     # 前端 HTML 页面
├── static/
│   ├── style.css      # 样式文件
│   └── app.js         # JavaScript 交互逻辑
├── uploads/           # 上传的图片
└── results/           # 标注结果图片
```

## 与 Gradio 版本的区别

1. **样式控制**：完全自定义 CSS，所有组件颜色、布局都可精确控制
2. **更轻量**：不依赖 Gradio，启动更快
3. **更灵活**：可以自由添加功能和修改界面
4. **流式输出**：使用 Server-Sent Events (SSE) 实现流式响应

## 开发说明

- 修改样式：编辑 `static/style.css`
- 修改布局：编辑 `templates/index.html`
- 修改交互：编辑 `static/app.js`
- 修改后端：编辑 `app.py`

所有修改无需重启服务器（除非修改 Python 代码）。

