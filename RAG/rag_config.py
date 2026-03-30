"""RAG 配置与路径工具：集中管理 RAG 相关的默认参数与目录结构。

RAG configuration and path utilities: centralize default parameters and
directories for retrieval-augmented generation (RAG).
"""

from __future__ import annotations

from pathlib import Path

from config import config


BASE_DIR: Path = Path(__file__).resolve().parent.parent
RAG_DIR: Path = BASE_DIR / "RAG"
DOCS_DIR: Path = RAG_DIR / "docs"
INDEX_DIR: Path = RAG_DIR / "index"

# 是否默认启用 RAG（可由前端按钮覆盖）/
# Whether to enable RAG by default (can be overridden by the frontend).
RAG_ENABLED_DEFAULT: bool = False

# 嵌入模型名称与服务端信息 /
# Embedding model name; typically hosted on the same Ollama server as chat models.
EMBED_MODEL_NAME: str = "qwen3-embedding:8b"


def get_ollama_base_url() -> str:
    """返回 Ollama 服务器的 base_url（默认复用全局 LLM 配置）。

    Return Ollama server base_url, reusing global LLM config by default.
    """
    return getattr(config.llm, "base_url", "http://127.0.0.1:11434")


# 检索相关默认参数 / Default retrieval parameters
TOP_K: int = 4
MAX_CONTEXT_CHARS: int = 3000


def ensure_rag_directories() -> None:
    """确保 RAG 相关目录存在 / Ensure required RAG directories exist.

    - docs/: 原始文档目录（由用户手动放入文档，本函数仅创建空目录）/
      directory for raw docs; user is responsible for adding files.
    - index/: 向量索引目录（由 build_index.py 构建 FAISS 索引）/
      directory for FAISS vector index built by build_index.py.
    """
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

