"""
SecureAgent MCP 服务器：通过 MCP 协议暴露搜索、爬虫、文件与 Shell 工具。

SecureAgent MCP Server: exposes web search, web crawler, file, and shell
tools via the Model Context Protocol.
Run: python -m mcp_server.server [--transport stdio|sse]
"""

import argparse
import os
import sys
from typing import Optional

# 确保项目根目录在 sys.path 中 / Ensure project root is in sys.path
_secure_agent_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _secure_agent_root not in sys.path:
    sys.path.insert(0, _secure_agent_root)
os.chdir(_secure_agent_root)

from mcp.server.fastmcp import FastMCP

from utils.logger import logger
from mcp_server.tools import file_tools
from mcp_server.tools import shell_tools

# 延迟导入工具实例 / Lazy-import tool instances
def _get_search_tool():
    from mcp_server.tools.web_search import _search_tool_instance
    return _search_tool_instance

def _get_crawler():
    from mcp_server.tools.web_crawler import _crawler
    return _crawler

# 创建 FastMCP 实例 / Create FastMCP instance
mcp = FastMCP("SecureAgent", json_response=True)


# ----- 搜索与爬虫工具 / Web search & crawler tools -----

@mcp.tool()
def web_search(query: str, num_results: int = 5) -> str:
    """Quick web search. Returns titles, URLs and brief descriptions. Use for simple lookups."""
    logger.info("[MCP Server] 工具 web_search 被调用 query=%s num_results=%s", query[:80], num_results)
    return _get_search_tool().search(query, num_results=num_results)


@mcp.tool()
def web_search_with_content(query: str, num_results: int = 3, timeout: int = 8) -> str:
    """Deep web search: searches and fetches full content from top results. Use for research and summarization."""
    logger.info("[MCP Server] 工具 web_search_with_content 被调用 query=%s", query[:80])
    return _get_search_tool().search(
        query,
        num_results=num_results,
        fetch_content=True,
        content_max_length=4000,
        fetch_timeout=timeout,
    )


@mcp.tool()
def fetch_webpage(url: str, max_length: int = 10000) -> str:
    """Fetch and extract main text content from a webpage URL. Use when you have a specific URL to read."""
    logger.info("[MCP Server] 工具 fetch_webpage 被调用 url=%s", url[:80])
    result = _get_crawler().fetch(url, mode="auto", max_length=max_length)
    if result.success:
        return f"📄 标题: {result.title}\n🔗 URL: {result.url}\n📊 内容长度: {result.word_count} 字符\n\n{'='*50}\n\n{result.content}"
    return f"❌ 无法获取网页内容\nURL: {url}\n错误: {result.error}"


@mcp.tool()
def fetch_and_summarize_url(url: str) -> str:
    """Fetch a webpage and prepare its content for summarization. Use when asked to summarize a specific URL."""
    logger.info("[MCP Server] 工具 fetch_and_summarize_url 被调用 url=%s", url[:80])
    result = _get_crawler().fetch(url, mode="auto", max_length=12000)
    if result.success:
        return (
            f"📄 网页标题: {result.title}\n🔗 URL: {result.url}\n\n"
            f"以下是网页的主要内容，请进行总结:\n\n{'='*50}\n\n{result.content}\n\n{'='*50}\n"
            "请根据以上内容提供一个简洁的总结。"
        )
    return f"❌ 无法获取网页内容进行总结\nURL: {url}\n错误: {result.error}"


# ----- 文件与通用工具 / File & common tools -----

@mcp.tool()
def read_file(path: str) -> str:
    """Read and return the full content of a text file. If the file is located on the desktop, you must call get_desktop_path() first to construct the correct absolute path. Path must comply with workspace root constraints."""
    logger.info("[MCP Server] 工具 read_file 被调用 path=%s", path)
    return file_tools.read_file(path)


@mcp.tool()
def write_file(path: str, content: str, append: bool = False) -> str:
    """Write text content to a specific file path.

    ARGS:
        path: Full path to the file (e.g., result of get_desktop_path() + '/filename.txt').
        content: THE ACTUAL BODY TEXT to write into the file. If saving a summary, this must be the summary text itself. If the user speaks Chinese, this content MUST be in Chinese. DO NOT put a description of the task here (e.g., DO NOT write "I found the news..." or "The file is created").
        append: False=overwrite/new, True=append.

    USAGE FOR DESKTOP: You must first call get_desktop_path()."""
    logger.info("[MCP Server] 工具 write_file 被调用 path=%s append=%s", path, append)
    return file_tools.write_file(path, content, append)


@mcp.tool()
def list_directory(path: str) -> str:
    """Retrieve a list of all files and subdirectories within a given path. Use this to verify file existence or explore folder structures. For desktop exploration, prefix with get_desktop_path(). Path must comply with workspace root constraints."""
    logger.info("[MCP Server] 工具 list_directory 被调用 path=%s", path)
    return file_tools.list_directory(path)


@mcp.tool()
def get_desktop_path() -> str:
    """Return the absolute directory path of the current user's desktop. MANDATORY PREREQUISITE: You MUST call this tool first whenever a user asks to 'create', 'save', 'write', or 'put' any file on the desktop. Use the returned path as the base for the 'path' argument in write_file."""
    return file_tools.get_desktop_path()


@mcp.tool()
def get_current_datetime(timezone: Optional[str] = None) -> str:
    """Return current date and time as ISO string. Use for timestamps in notes or filenames."""
    return file_tools.get_current_datetime(timezone)


@mcp.tool()
def get_workspace_root() -> str:
    """Return the allowed file operation root directory. Use to know where you can read/write files."""
    return file_tools.get_workspace_root()


# ----- Shell 工具（受限命令执行）/ Shell tools (restricted command execution) -----

@mcp.tool()
def run_shell_command(command: str, timeout: int = 10) -> str:
    """Execute a shell command in a restricted sandbox. Only allowlisted commands (curl, wget, python, node, jq, grep, etc.) can run. Returns stdout, stderr and exit_code. Use this when a Skill's SKILL.md contains command-line examples that need to be executed."""
    logger.info("[MCP Server] 工具 run_shell_command 被调用 command=%s", command[:120])
    result = shell_tools.run_shell_command(command, timeout=timeout)
    parts = []
    if result.get("stdout"):
        parts.append(f"stdout:\n{result['stdout']}")
    if result.get("stderr"):
        parts.append(f"stderr:\n{result['stderr']}")
    parts.append(f"exit_code: {result.get('exit_code', -1)}")
    return "\n".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SecureAgent MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport: stdio (local) or sse (HTTP SSE)",
    )
    return parser.parse_args()


def run_server(transport: str = "stdio") -> None:
    mcp.run(transport=transport)


if __name__ == "__main__":
    args = parse_args()
    run_server(transport=args.transport)
