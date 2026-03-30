"""
Agent模块

包含SecureAgent的核心实现
"""

from .secure_agent import (
    SecureAgent,
    create_agent,
    run_with_mcp_async,
    get_web_mcp_agent,
    get_current_web_mcp_source,
    switch_web_mcp_source,
    get_web_prompt_sandbox_enabled,
    set_web_prompt_sandbox_enabled,
)

__all__ = [
    "SecureAgent",
    "create_agent",
    "run_with_mcp_async",
    "get_web_mcp_agent",
    "get_current_web_mcp_source",
    "switch_web_mcp_source",
    "get_web_prompt_sandbox_enabled",
    "set_web_prompt_sandbox_enabled",
]
