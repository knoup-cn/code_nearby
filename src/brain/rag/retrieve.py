"""Retrieval: multi-channel recall + RRF fusion + graph boost (C2/C3/C4).

Two lexical recall channels (BM25 over content, trigram over symbols) are fused
with Reciprocal Rank Fusion and de-duplicated, then nudged by a lightweight
dependency-proximity boost from the existing ``_GRAPH.json`` (Aider-style
structural ranking). Optional synonym expansion and heuristic reranking improve
natural-language query recall without embeddings.
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
    expand_synonyms: bool = False,
    enable_rerank: bool = False,
) -> list[ScoredChunk]:
    """Return the top-``k`` chunks for a query, fused across channels.

    ``language`` / ``path_glob`` filter at the SQL level (C4). ``graph`` enables
    the dependency-proximity boost (C3 structural signal) when provided.

    ``expand_synonyms`` expands the query with code-domain synonyms before
    retrieval (zero-cost, no embedding). ``enable_rerank`` applies heuristic
    score adjustments after fusion.
    """
    recall = recall or max(k * 4, 20)

    # 可选：同义词扩展
    search_query = query
    if expand_synonyms:
        from brain.rag.synonyms import expand_query

        search_query = expand_query(query)

    bm25_ids = index.query_bm25(search_query, recall, language, path_glob)
    symbol_ids = index.query_symbol(search_query, recall, language, path_glob)

    scores = rrf_fuse([bm25_ids, symbol_ids], [BM25_WEIGHT, SYMBOL_WEIGHT])
    if not scores:
        return []
    if graph:
        apply_graph_boost(scores, graph)

    ranked_ids = sorted(scores, key=lambda cid: (-scores[cid], cid))[:k]
    chunks = {c.chunk_id: c for c in index.get_chunks(ranked_ids)}
    results = [
        ScoredChunk(chunk=chunks[cid], score=round(scores[cid], 6))
        for cid in ranked_ids
        if cid in chunks
    ]

    # 可选：启发式重排
    if enable_rerank:
        results = rerank_heuristic(results, query)

    return results


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


def rerank_heuristic(scored: list[ScoredChunk], query: str) -> list[ScoredChunk]:
    """启发式分数微调——零成本提升排序质量。

    在 RRF 融合后做小幅加分（所有调整均相加，保守幅度）：

    1. 精确符号名命中查询词 → +0.05
    2. qualified_name 包含查询词 → +0.03
    3. 多个查询词命中内容 → +0.01 × (命中数-1)
    4. 有 docstring → +0.02
    5. 浅层级（顶层 API 优先）→ +0.01
    """
    query_terms = set(query.lower().split())
    adjusted: list[ScoredChunk] = []

    for sc in scored:
        score = sc.score
        content_lower = sc.chunk.content.lower()
        sig_lower = sc.chunk.signature.lower()

        # 1. 精确符号名命中
        if sc.chunk.symbol.lower() in query_terms:
            score += 0.05

        # 2. qualified_name 包含查询词
        qname_lower = sc.chunk.qualified_name.lower()
        if qname_lower and any(t in qname_lower for t in query_terms):
            score += 0.03

        # 3. 多词命中密度
        hits = sum(1 for t in query_terms if t in content_lower or t in sig_lower)
        if hits > 1:
            score += 0.01 * (hits - 1)

        # 4. 有文档
        if sc.chunk.docstring:
            score += 0.02

        # 5. 浅层级优先（每层 0.01，最多 0.05）
        depth = sc.chunk.qualified_name.count(".") if sc.chunk.qualified_name else 0
        score += 0.01 * (1.0 / max(1, depth))

        adjusted.append(ScoredChunk(chunk=sc.chunk, score=round(score, 6)))

    # 按调整后的分数重排
    adjusted.sort(key=lambda s: (-s.score, s.chunk.chunk_id))
    return adjusted


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
