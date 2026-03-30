"""
SecureAgent MCP 服务器包。
SecureAgent MCP Server package.
Run: python -m mcp_server.server [--transport stdio|sse]
"""

from mcp_server.server import run_server, parse_args

__all__ = ["run_server", "parse_args"]
