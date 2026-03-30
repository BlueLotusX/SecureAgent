"""
RAG 索引构建脚本：扫描文档目录并构建 FAISS 向量索引。

RAG index builder: scans the docs directory and builds a FAISS vector
index using OllamaEmbeddings.

用法（在 SecureAgent 根目录）/ Usage (from SecureAgent root):
    python -m RAG.build_index

行为 / Behavior:
- 扫描 RAG/docs/ 下的文本类文件 / Scans text files under RAG/docs/.
- 使用 OllamaEmbeddings 生成向量 / Generates embeddings via OllamaEmbeddings.
- 使用 FAISS 构建向量索引并保存到 RAG/index/ / Builds and saves a FAISS index to RAG/index/.

注意 / Note:
- 本脚本不会写入统一日志，仅在控制台打印简单进度信息。
  This script only prints progress to the console; it does not use the unified logger.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .rag_config import (
    DOCS_DIR,
    INDEX_DIR,
    EMBED_MODEL_NAME,
    get_ollama_base_url,
    ensure_rag_directories,
)


def _iter_text_files(root: Path) -> List[Path]:
    """递归收集目录下所有文本文件（.txt / .md）。

    Recursively collect all text files (.txt / .md) under the given root.
    """
    exts = {".txt", ".md"}
    files: List[Path] = []
    if not root.exists():
        return files
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            files.append(p)
    return files


def _load_documents() -> List[Document]:
    """从 DOCS_DIR 加载所有文本文件并包装为 Document 对象。

    Load all text files from DOCS_DIR and wrap them as Document objects.
    """
    files = _iter_text_files(DOCS_DIR)
    docs: List[Document] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not text.strip():
            continue
        rel = f.relative_to(DOCS_DIR)
        docs.append(
            Document(
                page_content=text,
                metadata={
                    "source": os.fspath(rel),
                },
            )
        )
    return docs


def build_index() -> None:
    """构建 FAISS 向量索引：加载文档 → 切分 → 嵌入 → 保存索引。

    Build the FAISS vector index: load docs → split → embed → save index.
    """
    print("=== RAG: 开始构建向量索引 ===")
    ensure_rag_directories()
    raw_docs = _load_documents()
    if not raw_docs:
        print(f"[RAG] 警告：在 {DOCS_DIR} 下未找到任何文本文件，索引不会被更新。")
        return

    print(f"[RAG] 已加载原始文档数量: {len(raw_docs)}")

    # 将长文档切分为较小 chunk，避免超过嵌入模型上下文窗口 /
    # Split long documents into smaller chunks to stay within the embedding model context window.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=2000,      # 约 2K 字符一块 / ~2K chars per chunk
        chunk_overlap=200,    # 适当重叠，利于语义连续 / Overlap for semantic continuity
    )
    docs = splitter.split_documents(raw_docs)
    print(f"[RAG] 切分后的文档块数量: {len(docs)}")

    base_url = get_ollama_base_url()
    print(f"[RAG] 使用嵌入模型: {EMBED_MODEL_NAME} @ {base_url}")
    embeddings = OllamaEmbeddings(model=EMBED_MODEL_NAME, base_url=base_url)

    print(f"[RAG] 正在构建 FAISS 向量索引...")
    vector_store = FAISS.from_documents(docs, embeddings)

    print(f"[RAG] 正在保存索引到目录: {INDEX_DIR}")
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    vector_store.save_local(os.fspath(INDEX_DIR))

    print("=== RAG: 向量索引构建完成 ===")


if __name__ == "__main__":
    build_index()

