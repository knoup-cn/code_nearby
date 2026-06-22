"""Goal-2 code-RAG stack: lexical + structural retrieval.

This subpackage implements brain's "context engine" (Goal 2 in
``docs/CAPABILITY_MATRIX.md``): tree-sitter chunking + SQLite FTS5 lexical recall
+ structural (graph) ranking, returning token-budgeted code chunks with
``file:line`` citations. It is built alongside the existing Goal-1 products
(Markdown summaries + ``_GRAPH.json``), which are left untouched.

Embeddings / dense retrieval are intentionally deferred to an opt-in 进阶 layer
(see the capability matrix); nothing here downloads a model or runs a vector DB.

Synonym expansion supports three-layer fallback: custom dict → built-in clusters
→ embed model (opt-in, ``fastembed>=0.4``).
"""

from __future__ import annotations

from brain.rag.synonyms import expand_query, is_embed_available, load_custom_synonyms

__all__ = ["expand_query", "is_embed_available", "load_custom_synonyms"]
