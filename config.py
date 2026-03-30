"""配置管理模块：集中管理 LLM、搜索、Agent 与 MCP 等运行配置。

Configuration module: centralizes runtime configuration for LLM, search,
agent behavior and MCP connectivity.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import os


@dataclass
class LLMConfig:
    """LLM 配置 / LLM configuration."""
    base_url: str = "http://127.0.0.1:11434"
    # 聊天模型名称，不可为嵌入模型；为空时回退为 "qwen3:8b"
    # Chat model name (must not be an embedding model); falls back to "qwen3:8b" if empty
    model: str = "qwen3:8b"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 120


@dataclass
class SearchConfig:
    """搜索配置 / Web search configuration."""
    # 首选搜索引擎 / Preferred search engine
    engine: str = "duckduckgo"
    # 备用引擎顺序 / Fallback engine order
    fallback_engines: List[str] = field(default_factory=lambda: ["bing", "baidu", "google"])
    # 搜索结果数量 / Number of search results
    num_results: int = 5
    # 搜索语言 / Search language
    lang: str = "en"
    # 搜索地区 / Search region
    country: str = "us"
    # 重试延迟（秒）/ Retry delay in seconds
    retry_delay: int = 60
    # 最大重试次数 / Maximum retries
    max_retries: int = 3


@dataclass
class AgentConfig:
    """Agent 配置 / Agent behavior configuration."""
    name: str = "SecureAgent"
    description: str = "一个具有网络搜索能力的智能Agent"
    max_steps: int = 10
    # 工作目录 / Workspace root directory
    workspace_root: str = field(default_factory=lambda: os.getcwd())
    # 可选节点开关 / Optional node switches
    reflection_switch: bool = True  # 反思节点 / Reflection node
    memory_switch: bool = True       # 记忆节点 / Memory node
    # Skills System 开关 / Skills System toggle (default off)
    enable_skills: bool = False
    # 技能源目录 / Skill source directories (virtual paths relative to workspace_root)
    skills_sources: List[str] = field(default_factory=lambda: ["/skills/"])
    # 启用 Skills 的节点列表 / Nodes that have Skills enabled
    skills_enabled_agents: List[str] = field(default_factory=lambda: ["decision"])


@dataclass
class MCPConfig:
    """MCP 配置 / MCP connection configuration."""
    # 是否通过 MCP 加载工具 / Whether to load tools via MCP
    use_mcp: bool = True
    # 传输方式 / Transport: "stdio" or "sse"
    transport: str = "stdio"
    # stdio 启动命令 / stdio launch command
    command: str = "python"
    # stdio 命令参数 / stdio command args
    args: List[str] = field(default_factory=lambda: ["-m", "mcp_server.server"])
    # SSE 模式 URL / SSE mode MCP Server URL
    url: str = "http://127.0.0.1:8000/sse"
    # 云端 MCP URL（可用环境变量 MCP_CLOUD_URL 覆盖）/ Cloud MCP URL (overridable via MCP_CLOUD_URL env var)
    mcp_cloud_url: Optional[str] = field(
        default_factory=lambda: os.environ.get(
            "MCP_CLOUD_URL",
            # IMPORTANT: replace this placeholder with your own Bright Data token.
            # Use environment variable MCP_CLOUD_URL to avoid hardcoding secrets.
            "https://mcp.brightdata.com/sse?token=[YOUR_API_KEY]",
        )
    )
    # 文件工具允许的根目录 / Allowed root for file tools (None → agent.workspace_root)
    allowed_file_root: Optional[str] = None


@dataclass
class Config:
    """全局配置对象 / Global configuration container."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)


# 全局配置实例 / Global config singleton
config = Config()


def update_config(**kwargs):
    """按模块更新全局配置 / Update global config by named sections."""
    global config
    if "llm" in kwargs:
        for key, value in kwargs["llm"].items():
            setattr(config.llm, key, value)
    if "search" in kwargs:
        for key, value in kwargs["search"].items():
            setattr(config.search, key, value)
    if "agent" in kwargs:
        for key, value in kwargs["agent"].items():
            setattr(config.agent, key, value)
    if "mcp" in kwargs:
        for key, value in kwargs["mcp"].items():
            setattr(config.mcp, key, value)
