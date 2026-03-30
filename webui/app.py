"""SecureAgent Web UI 后端：提供浏览器界面与后端 API。

SecureAgent Web UI backend: serves the HTML UI and exposes HTTP APIs
(`/api/chat`, `/api/info`, etc.) for interacting with the agent.
"""

import sys
import os
from pathlib import Path

_current_dir = Path(__file__).parent
_parent_dir = _current_dir.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

import json
import logging
import threading
from queue import Queue, Empty

from flask import Flask, render_template, request, jsonify, Response, stream_with_context

logging.getLogger("werkzeug").setLevel(logging.WARNING)
from agent import (
    SecureAgent,
    get_web_mcp_agent,
    get_current_web_mcp_source,
    switch_web_mcp_source,
    get_web_prompt_sandbox_enabled,
    set_web_prompt_sandbox_enabled,
)
from RAG.rag_config import RAG_ENABLED_DEFAULT
from config import config
from utils.logger import logger
from mcp_server.tools.web_search import set_interactive_mode

app = Flask(
    __name__,
    template_folder=str(_current_dir / 'templates'),
    static_folder=str(_current_dir / 'static'),
)

_agent: SecureAgent = None  # 全局 Agent 单例 / Global agent singleton


def get_agent() -> SecureAgent:
    """获取或创建 Agent 实例 / Get or create shared SecureAgent instance.

    工具仅通过 MCP 提供，无本地工具回退。/
    Tools are provided exclusively via MCP; no local-tool fallback.
    """
    global _agent
    if _agent is None:
        logger.info("正在初始化Agent（MCP）...")
        set_interactive_mode(False)
        if not getattr(config.mcp, "use_mcp", True):
            raise RuntimeError("当前仅支持 MCP 模式，请在 config 中设置 use_mcp=True")
        _agent = get_web_mcp_agent(timeout=60.0)
        logger.info(f"Agent初始化完成（MCP），模型: {_agent.model_name}")
    return _agent


@app.route('/')
def index():
    """首页 / Render index page."""
    return render_template('index.html')


@app.route('/api/info')
def get_info():
    """
    获取 Agent 信息（MCP 来源、沙盒状态等）。
    Get Agent info (MCP source, sandbox status, etc.).
    """
    try:
        agent = get_agent()
        return jsonify({
            'success': True,
            'model': agent.model_name,
            'tools': [t.name for t in agent.tools],
            'mcp_source': get_current_web_mcp_source(),
            'prompt_sandbox_enabled': get_web_prompt_sandbox_enabled(),
            'rag_enabled_default': RAG_ENABLED_DEFAULT,
            'skills_enabled': bool(getattr(config.agent, "enable_skills", False)),
        })
    except Exception as e:
        logger.error(f"获取Agent信息失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'model': '未知',
            'mcp_source': get_current_web_mcp_source(),
            'prompt_sandbox_enabled': get_web_prompt_sandbox_enabled(),
            'rag_enabled_default': RAG_ENABLED_DEFAULT,
            'skills_enabled': bool(getattr(config.agent, "enable_skills", False)),
        })


@app.route('/api/chat', methods=['POST'])
def chat():
    """
    处理聊天请求（支持流式和非流式）。
    Handle chat request (supports both streaming and non-streaming).
    """
    try:
        data = request.json
        message = data.get('message', '').strip()
        session_id = data.get('session_id', 'default')
        stream = data.get('stream', False)
        use_rag = data.get('use_rag', None)

        if not message:
            return jsonify({
                'success': False,
                'error': '消息不能为空'
            })

        if stream:
            return _chat_stream(message, session_id, use_rag)

        logger.info(f"收到消息: {message[:50]}...")
        agent = get_agent()
        response = agent.chat(message, session_id=session_id, use_rag=use_rag)
        return jsonify({
            'success': True,
            'response': response
        })
    except Exception as e:
        logger.error(f"处理聊天请求失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


def _chat_stream(message: str, session_id: str, use_rag=None):
    """
    流式聊天：推送节点状态事件，最后推送 done + response。
    Streaming chat: push node status events, then done + final response.
    """
    status_queue = Queue()

    def status_callback(status: str, detail: str = None, extra: dict = None):
        extra = extra or {}
        status_queue.put({
            "status": status,
            "detail": detail or "",
            "content": extra.get("content", ""),
            "duration_sec": extra.get("duration_sec"),
        })

    def run_chat():
        try:
            agent = get_agent()
            result = agent.chat(message, session_id=session_id, status_callback=status_callback, use_rag=use_rag)
            status_queue.put({"status": "done", "response": result})
        except Exception as e:
            logger.exception("流式 chat 执行异常")
            status_queue.put({"status": "error", "error": str(e)})

    thread = threading.Thread(target=run_chat)
    thread.start()

    def generate():
        while True:
            try:
                item = status_queue.get(timeout=300)
            except Empty:
                yield json.dumps({"status": "timeout", "error": "timeout"}) + "\n"
                break
            if item.get("status") == "done":
                yield json.dumps({"status": "done", "response": item.get("response", "")}) + "\n"
                break
            if item.get("status") == "error":
                yield json.dumps({"status": "error", "error": item.get("error", "")}) + "\n"
                break
            payload = {"status": item["status"], "detail": item.get("detail", "")}
            if item.get("content") is not None and item.get("content") != "":
                payload["content"] = item["content"]
            if item.get("duration_sec") is not None:
                payload["duration_sec"] = item["duration_sec"]
            yield json.dumps(payload) + "\n"

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route('/api/clear', methods=['POST'])
def clear():
    """
    清空对话历史。
    Clear conversation history and reset agent session.
    """
    try:
        global _agent
        if _agent:
            _agent.reset()
            logger.info("对话历史已清空")

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"清空对话失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/mcp/switch', methods=['POST'])
def mcp_switch():
    """
    切换 MCP 来源（local / cloud），触发重连并清空对话。
    Switch MCP source (local / cloud); triggers reconnect and clears conversation.
    """
    try:
        data = request.get_json() or {}
        source = data.get('source', '').strip().lower()
        if source not in ('local', 'cloud'):
            return jsonify({
                'success': False,
                'error': "source 必须为 'local' 或 'cloud'",
            }), 400
        global _agent
        switch_web_mcp_source(source)
        _agent = None
        agent = get_web_mcp_agent(timeout=90.0)
        if agent:
            agent.reset()
            _agent = agent
        return jsonify({
            'success': True,
            'source': source,
            'message': '已切换 MCP，对话已清空',
        })
    except Exception as e:
        logger.exception("切换 MCP 失败: %s", e)
        return jsonify({
            'success': False,
            'error': str(e),
        }), 500


@app.route('/api/security/prompt_sandbox/toggle', methods=['POST'])
def toggle_prompt_sandbox():
    """
    切换提示词沙盒防御开关，触发 MCP 重连。
    Toggle prompt sandbox defense; triggers MCP reconnect.
    """
    try:
        set_web_prompt_sandbox_enabled(not get_web_prompt_sandbox_enabled())
        # 触发重连以应用新状态 / Trigger reconnect to apply new state
        switch_web_mcp_source(get_current_web_mcp_source())
        global _agent
        _agent = None
        return jsonify({
            'success': True,
            'prompt_sandbox_enabled': get_web_prompt_sandbox_enabled(),
        })
    except Exception as e:
        logger.exception("切换提示词防御失败: %s", e)
        return jsonify({
            'success': False,
            'error': str(e),
            'prompt_sandbox_enabled': get_web_prompt_sandbox_enabled(),
        }), 500


@app.route('/api/skills/toggle', methods=['POST'])
def toggle_skills():
    """
    切换 Skills System 开关，触发 MCP 重连。
    Toggle Skills System; triggers MCP reconnect.
    """
    try:
        # 翻转开关 / Toggle the flag
        current = bool(getattr(config.agent, "enable_skills", False))
        setattr(config.agent, "enable_skills", not current)
        # 触发重连以应用新状态 / Trigger reconnect to apply new state
        switch_web_mcp_source(get_current_web_mcp_source())
        global _agent
        _agent = None
        return jsonify({
            'success': True,
            'skills_enabled': bool(getattr(config.agent, "enable_skills", False)),
        })
    except Exception as e:
        logger.exception("切换 Skills System 失败: %s", e)
        return jsonify({
            'success': False,
            'error': str(e),
            'skills_enabled': bool(getattr(config.agent, "enable_skills", False)),
        }), 500


def main():
    """Web UI 主函数 / Web UI main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='SecureAgent Web UI')
    parser.add_argument('--port', type=int, default=7860, help='服务端口')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='服务地址')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🤖 SecureAgent Web UI")
    print("=" * 60)
    print(f"启动服务: http://{args.host}:{args.port}")
    print("=" * 60)
    print("提示: 首次加载可能需要初始化Agent，请稍候...")
    print("按 Ctrl+C 停止服务")
    print("=" * 60 + "\n")
    
    # 预加载 Agent / Preload agent
    try:
        get_agent()
    except Exception as e:
        print(f"⚠️ Agent预加载失败: {e}")
        print("服务仍将启动，但首次请求可能较慢")
    
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
    )


if __name__ == '__main__':
    main()
