# CogAgent Client Web UI

基于 Flask + HTML/CSS/JavaScript 的 CogAgent 客户端界面，完全替代原有的 Gradio 版本 `client.py`。

## 特性

- ✅ 布局与 `inference/webui` 完全一致
- ✅ 功能与原 `client.py` (Gradio版) 完全一致
- ✅ 图片上传（支持拖拽）
- ✅ 自动截图、调用模型、执行操作循环
- ✅ 聊天历史记录显示
- ✅ 边界框标注图片
- ✅ 参数滑块（Maximum Length, Top P, Temperature）
- ✅ 停止执行功能
- ✅ 清空历史功能

## 运行命令

### 第一步：在服务器端启动模型服务（与原来一样）

```bash
python app/openai_demo.py --model_path THUDM/cogagent-9b-20241220 --host 0.0.0.0 --port 7870
```

### 第二步：在本地启动客户端

**原来的命令 (Gradio版)：**
```bash
python app/client.py --api_key EMPTY --base_url http://127.0.0.1:7870/v1 --client_name 127.0.0.1 --client_port 7860 --model CogAgent
```

**新的命令 (Flask版)：**
```bash
python app/webui/app.py --api_key EMPTY --base_url http://127.0.0.1:7870/v1 --host 127.0.0.1 --port 7860 --model CogAgent
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--api_key` | EMPTY | API密钥 |
| `--base_url` | http://127.0.0.1:7870/v1 | 服务端API地址 |
| `--model` | CogAgent | 模型名称 |
| `--host` | 127.0.0.1 | 客户端Web服务地址 |
| `--port` | 7860 | 客户端Web服务端口 |
| `--platform` | 自动检测 | 平台类型 (WIN/Mac/Mobile) |

## 访问界面

启动后在浏览器访问：http://127.0.0.1:7860

## 对比原版 client.py

| 组件 | 原版 (Gradio) | 新版 (Flask) |
|------|--------------|--------------|
| Chatbot | ✅ | ✅ |
| Image (标注图) | ✅ | ✅ |
| Task 输入框 | ✅ | ✅ |
| Submit 按钮 | ✅ | ✅ |
| Clear History 按钮 | ✅ | ✅ |
| Stop 按钮 | ✅ | ✅ |
| Maximum Length 滑块 | ✅ | ✅ |
| Top P 滑块 | ✅ | ✅ |
| Temperature 滑块 | ✅ | ✅ |
| 自动截图执行 | ✅ | ✅ |
| 最大15轮限制 | ✅ | ✅ |

## 文件结构

```
app/webui/
├── app.py              # Flask 后端服务器
├── README.md           # 说明文档
├── templates/
│   └── index.html      # 前端页面（与 inference/webui 布局一致）
├── static/
│   ├── style.css       # 样式文件（与 inference/webui 一致）
│   └── app.js          # JavaScript 交互逻辑
├── caches/             # 截图缓存目录
└── uploads/            # 上传图片目录
```

## 工作流程

1. 用户输入任务描述
2. 点击 Submit 按钮
3. 系统自动：
   - 截取当前屏幕
   - 发送给远程模型
   - 获取操作指令
   - 执行鼠标/键盘操作
   - 循环直到任务完成或达到15轮
4. 可随时点击 Stop 停止执行
5. 点击 Clear All History 清空历史

## 注意事项

⚠️ AI 会控制你的鼠标和键盘，执行期间请勿触碰电脑
