"""
运行时 RAG 检索服务：从本地文档向量索引中检索相关片段并注入决策上下文。

Runtime RAG retrieval service: lazily loads the vector index built from
local docs and exposes `get_rag_context(query)` to provide context for
the Decision agent before choosing tools.
"""

from __future__ import annotations

from typing import List, Optional

import os

from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from utils.logger import logger
from .rag_config import (
    INDEX_DIR,
    EMBED_MODEL_NAME,
    TOP_K,
    MAX_CONTEXT_CHARS,
    get_ollama_base_url,
    ensure_rag_directories,
)


_EMBEDDINGS: Optional[OllamaEmbeddings] = None
_VECTOR_STORE: Optional[FAISS] = None
_VECTOR_STORE_LOADED: bool = False


def _get_embeddings() -> OllamaEmbeddings:
    """懒加载嵌入模型 / Lazily initialize the embedding model."""
    global _EMBEDDINGS
    if _EMBEDDINGS is None:
        base_url = get_ollama_base_url()
        logger.info(f"[RAG] 初始化嵌入模型: {EMBED_MODEL_NAME} @ {base_url}")
        _EMBEDDINGS = OllamaEmbeddings(model=EMBED_MODEL_NAME, base_url=base_url)
    return _EMBEDDINGS


def ensure_vector_store_loaded() -> bool:
    """懒加载向量索引 / Lazily load the FAISS vector store.

    Returns:
        bool: 是否加载成功（若索引不存在或加载失败返回 False）/
        True if the index was loaded successfully, False otherwise.
    """
    global _VECTOR_STORE, _VECTOR_STORE_LOADED

    if _VECTOR_STORE_LOADED and _VECTOR_STORE is not None:
        return True

    ensure_rag_directories()
    if not INDEX_DIR.exists():
        logger.info("[RAG] 向量索引目录不存在，跳过 RAG 检索")
        _VECTOR_STORE_LOADED = False
        return False

    # FAISS 使用目录保存索引文件，目录存在但内部可能为空 /
    # FAISS uses a directory to store index files; it may exist but be empty.
    has_files = any(INDEX_DIR.iterdir())
    if not has_files:
        logger.info("[RAG] 向量索引目录为空，跳过 RAG 检索")
        _VECTOR_STORE_LOADED = False
        return False

    try:
        embeddings = _get_embeddings()
        _VECTOR_STORE = FAISS.load_local(
            str(INDEX_DIR),
            embeddings,
            allow_dangerous_deserialization=True,
        )
        _VECTOR_STORE_LOADED = True
        logger.info("[RAG] 已从索引目录加载向量库: %s", os.fspath(INDEX_DIR))
        return True
    except Exception as e:
        logger.warning(f"[RAG] 加载向量索引失败，将禁用本次 RAG：{e}")
        _VECTOR_STORE = None
        _VECTOR_STORE_LOADED = False
        return False


def retrieve_docs(query: str, top_k: Optional[int] = None) -> List[Document]:
    """检索与 query 最相关的文档片段 / Retrieve top-k relevant document chunks."""
    if not query.strip():
        return []
    if not ensure_vector_store_loaded():
        return []

    k = top_k or TOP_K
    try:
        docs = _VECTOR_STORE.similarity_search(query, k=k)  # type: ignore[arg-type]
        return docs or []
    except Exception as e:
        logger.warning(f"[RAG] 相似度检索失败，将跳过本次 RAG：{e}")
        return []


def format_context(docs: List[Document], max_chars: Optional[int] = None) -> str:
    """将文档片段格式化为可注入决策 prompt 的上下文字符串。

    Format retrieved document chunks into a single context string suitable
    for injection into the Decision agent's prompt.
    """
    if not docs:
        return ""

    parts = []
    for i, doc in enumerate(docs, start=1):
        source = (doc.metadata or {}).get("source") or (doc.metadata or {}).get("path") or "unknown"
        title = (doc.metadata or {}).get("title") or ""
        header = f"[{i}] Source: {source}"
        if title:
            header += f" | Title: {title}"
        parts.append(f"{header}\n{doc.page_content.strip()}")

    text = "\n\n---\n\n".join(parts)
    limit = max_chars or MAX_CONTEXT_CHARS
    if len(text) > limit:
        text = text[: limit - 20] + "\n...[truncated]..."
    return text


def get_rag_context(query: str, top_k: Optional[int] = None, max_chars: Optional[int] = None) -> str:
    """对外主入口：根据用户 query 返回可注入的 RAG 上下文字符串。

    Main public entrypoint: return a formatted RAG context string for
    the given user query to be injected before tool selection.
    """
    query_clean = query.strip()
    if not query_clean:
        return ""

    docs = retrieve_docs(query_clean, top_k=top_k)
    if not docs:
        return ""

    context = format_context(docs, max_chars=max_chars)
    if context:
        logger.info("[RAG] 已为本轮请求注入上下文，片段数=%d，长度=%d 字符", len(docs), len(context))
    return context

