"""词汇+结构代码检索：tree-sitter 分块 + SQLite FTS5 + 依赖图排序。

同义词扩展支持三层 fallback：自定义 dict → 内置 clusters
→ embed 模型（可选，需 ``fastembed>=0.4``）。
"""

from __future__ import annotations

from brain.rag.synonyms import expand_query, is_embed_available, load_custom_synonyms

__all__ = ["expand_query", "is_embed_available", "load_custom_synonyms"]
