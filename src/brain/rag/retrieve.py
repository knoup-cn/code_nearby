"""Retrieval: multi-channel recall + RRF fusion + graph boost (C2/C3/C4).

Two lexical recall channels (BM25 over content, trigram over symbols) are fused
with Reciprocal Rank Fusion and de-duplicated, then nudged by a lightweight
dependency-proximity boost from the existing ``_GRAPH.json`` (Aider-style
structural ranking). No embeddings — dense recall slots in here later (进阶).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from brain.rag.index import RagIndex
from brain.rag.schema import Chunk

RRF_K = 60
BM25_WEIGHT = 1.0
SYMBOL_WEIGHT = 1.0
GRAPH_BOOST = 0.5 / (RRF_K + 1)  # < a single top rank's RRF contribution


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    chunk: Chunk
    score: float


def search(
    index: RagIndex,
    query: str,
    k: int = 5,
    *,
    language: str | None = None,
    path_glob: str | None = None,
    graph: dict | None = None,
    recall: int | None = None,
) -> list[ScoredChunk]:
    """Return the top-``k`` chunks for a query, fused across channels.

    ``language`` / ``path_glob`` filter at the SQL level (C4). ``graph`` enables
    the dependency-proximity boost (C3 structural signal) when provided.
    """
    recall = recall or max(k * 4, 20)
    bm25_ids = index.query_bm25(query, recall, language, path_glob)
    symbol_ids = index.query_symbol(query, recall, language, path_glob)

    scores = rrf_fuse([bm25_ids, symbol_ids], [BM25_WEIGHT, SYMBOL_WEIGHT])
    if not scores:
        return []
    if graph:
        apply_graph_boost(scores, graph)

    ranked_ids = sorted(scores, key=lambda cid: (-scores[cid], cid))[:k]
    chunks = {c.chunk_id: c for c in index.get_chunks(ranked_ids)}
    return [
        ScoredChunk(chunk=chunks[cid], score=round(scores[cid], 6))
        for cid in ranked_ids
        if cid in chunks
    ]


def rrf_fuse(
    ranked_lists: list[list[str]], weights: list[float], k: int = RRF_K
) -> dict[str, float]:
    """Reciprocal Rank Fusion: chunk_id -> fused score (de-dups across lists)."""
    scores: dict[str, float] = {}
    for ids, weight in zip(ranked_lists, weights, strict=True):
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (k + rank)
    return scores


def apply_graph_boost(scores: dict[str, float], graph: dict) -> None:
    """Boost chunks whose module neighbors the top hit's module (in place)."""
    if not scores:
        return
    module_by_source = {
        node["source_path"]: name
        for name, node in graph.get("nodes", {}).items()
        if node.get("type") == "module" and node.get("source_path")
    }
    if not module_by_source:
        return

    neighbors = _adjacency(graph.get("edges", []))

    def module_of(chunk_id: str) -> str | None:
        return module_by_source.get(chunk_id.split("::", 1)[0])

    top_chunk = max(scores, key=lambda cid: scores[cid])
    top_module = module_of(top_chunk)
    if top_module is None:
        return
    boost_modules = neighbors.get(top_module, set())

    for chunk_id in scores:
        module = module_of(chunk_id)
        if module is not None and module in boost_modules:
            scores[chunk_id] += GRAPH_BOOST


def _adjacency(edges: list[dict]) -> dict[str, set[str]]:
    """Undirected module adjacency from graph edges."""
    adj: dict[str, set[str]] = {}
    for edge in edges:
        src, dst = edge.get("from"), edge.get("to")
        if not src or not dst:
            continue
        adj.setdefault(src, set()).add(dst)
        adj.setdefault(dst, set()).add(src)
    return adj


def load_graph(project_kb_path: Path) -> dict | None:
    """Load ``_GRAPH.json`` from a project's knowledge base, if present."""
    graph_file = project_kb_path / "_GRAPH.json"
    if not graph_file.exists():
        return None
    try:
        return json.loads(graph_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
