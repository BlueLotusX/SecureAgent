"""
SecureAgent 命令行入口：支持交互式对话、单次查询和测试模式。

SecureAgent CLI entrypoint: provides interactive chat mode, single-query
mode, and a test mode for quick verification.
"""

import argparse
import asyncio
import sys
import os
from typing import Optional

# 确保本地模块可导入 / Ensure local modules are importable
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from agent import SecureAgent, run_with_mcp_async
from utils.logger import logger
from config import config, update_config
from mcp_server.tools.web_search import set_interactive_mode


def interactive_mode(agent: SecureAgent):
    """
    交互式对话模式 / Interactive chat mode.

    Args:
        agent: SecureAgent 实例 / SecureAgent instance.
    """
    print("\n" + "=" * 60)
    print("🤖 SecureAgent 交互式对话")
    print("=" * 60)
    print("输入你的问题，输入 'quit' 或 'exit' 退出")
    print("输入 'reset' 重置对话历史")
    print("输入 'search <关键词>' 进行网络搜索")
    print("-" * 60 + "\n")
    
    while True:
        try:
            user_input = input("👤 你: ").strip()
            
            if not user_input:
                continue
            
            # 退出 / Exit
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\n👋 再见！")
                break
            
            # 重置 / Reset
            if user_input.lower() == 'reset':
                agent.reset()
                print("🔄 对话历史已重置\n")
                continue
            
            # 处理请求 / Process request
            print("\n🤖 SecureAgent: ", end="")
            response = agent.chat(user_input)
            print(response)
            print()
            
        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except Exception as e:
            logger.error(f"发生错误: {e}")
            print(f"\n❌ 发生错误: {e}\n")


def single_query_mode(agent: SecureAgent, query: str):
    """
    单次查询模式 / Single-query mode.

    Args:
        agent: SecureAgent 实例 / SecureAgent instance.
        query: 用户查询 / User query string.
    """
    print("\n" + "=" * 60)
    print("🤖 SecureAgent 单次查询")
    print("=" * 60)
    print(f"📝 查询: {query}")
    print("-" * 60)
    
    response = agent.chat(query)
    
    print("\n📤 响应:")
    print(response)
    print("\n" + "=" * 60)


def test_mode(args):
    """
    测试模式：通过 MCP 连接 Agent 并验证基本功能。
    Test mode: connect Agent via MCP and verify basic functionality.
    """
    print("\n" + "=" * 60)
    print("🧪 SecureAgent 测试模式")
    print("=" * 60)

    def _run(agent):
        print("\n[测试1] Agent 已连接（MCP）")
        print(f"   模型: {agent.model_name}")
        print("\n[测试2] 简单对话...")
        r = agent.chat("你好，请用一句话介绍你自己。")
        print(f"   响应: {r[:200]}..." if len(r) > 200 else f"   响应: {r}")
        print("\n[测试3] 搜索测试...")
        agent.reset()
        r = agent.chat("请搜索一下 Python 3.12 的新特性有哪些？")
        print(f"   响应: {r[:300]}..." if len(r) > 300 else f"   响应: {r}")
        print("\n" + "=" * 60)
        print("🧪 测试完成")
        print("=" * 60)

    try:
        asyncio.run(
            run_with_mcp_async(
                _run,
                model=args.model,
                base_url=args.base_url,
                max_steps=getattr(args, "max_steps", 10),
            )
        )
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        print(f"\n❌ 测试失败: {e}")


def main():
    """CLI 主函数 / CLI main entry point."""
    parser = argparse.ArgumentParser(
        description="SecureAgent - 具有网络搜索能力的智能Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python main.py                           # 交互式对话
    python main.py --query "搜索Python教程"  # 单次查询
    python main.py --test                    # 测试模式
    python main.py --model llama3            # 指定模型
        """
    )
    
    parser.add_argument(
        "--query", "-q",
        type=str,
        help="单次查询内容"
    )
    
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="运行测试模式"
    )
    
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="指定使用的模型名称"
    )
    
    parser.add_argument(
        "--base-url", "-u",
        type=str,
        default="http://127.0.0.1:11434",
        help="Ollama服务器地址 (默认: http://127.0.0.1:11434)"
    )
    
    parser.add_argument(
        "--max-steps",
        type=int,
        default=10,
        help="最大执行步数 (默认: 10)"
    )
    
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="启用交互式搜索：每次搜索前询问用户选择搜索方式"
    )
    args = parser.parse_args()

    if args.interactive:
        set_interactive_mode(True)
        print("✓ 交互式搜索已启用")

    if args.test:
        test_mode(args)
        return

    run_fn = (
        (lambda a: single_query_mode(a, args.query))
        if args.query
        else interactive_mode
    )
    try:
        asyncio.run(
            run_with_mcp_async(
                run_fn,
                model=args.model,
                base_url=args.base_url,
                max_steps=args.max_steps,
            )
        )
    except Exception as e:
        logger.error(f"❌ MCP 失败: {e}")
        print(f"\n错误: {e}")
        print("提示: 若使用 transport=sse，请先启动: python -m mcp_server.server --transport sse")
        sys.exit(1)


if __name__ == "__main__":
    main()
