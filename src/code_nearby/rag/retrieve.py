"""检索：BM25 + trigram 双通道召回、RRF 融合、依赖图加分。

两个词汇召回通道（BM25 基于内容，trigram 基于符号名）通过
Reciprocal Rank Fusion 融合去重，再经 ``_GRAPH.json`` 依赖邻近度加分，
最后由启发式规则微调排序。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from code_nearby.rag.index import RagIndex
    from code_nearby.rag.schema import Chunk

from code_nearby.rag.synonyms import expand_query

RRF_K = 60
BM25_WEIGHT = 1.0
SYMBOL_WEIGHT = 1.0
GRAPH_BOOST = 0.5 / (RRF_K + 1)  # < 单个 top rank 的 RRF 贡献


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
    enable_expand: bool = True,
    enable_rerank: bool = True,
    enable_diversify: bool = True,
) -> list[ScoredChunk]:
    """返回 top-``k`` chunk，跨通道融合。

    ``language`` / ``path_glob`` 在 SQL 层过滤（C4）。传入 ``graph``
    启用依赖邻近度加分（C3 结构信号）。

    ``enable_expand`` 启用同义词扩展（C5），``enable_rerank``
    启用启发式微调排序（C1 贴近度）。
    """
    recall = recall or max(k * 4, 20)

    # 同义词扩展
    expanded_query = expand_query(query) if enable_expand else query

    bm25_ids = index.query_bm25(expanded_query, recall, language, path_glob)
    symbol_ids = index.query_symbol(expanded_query, recall, language, path_glob)

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

    # 启发式微调
    if enable_rerank:
        results = rerank_heuristic(results, query)

    # 跨文件多样性（确保 LLM 上下文覆盖不同模块）
    if enable_diversify:
        results = diversify(results)

    return results


def rrf_fuse(
    ranked_lists: list[list[str]], weights: list[float], k: int = RRF_K
) -> dict[str, float]:
    """Reciprocal Rank Fusion：chunk_id → 融合分数（跨列表去重）。"""
    scores: dict[str, float] = {}
    for ids, weight in zip(ranked_lists, weights, strict=True):
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (k + rank)
    return scores


def apply_graph_boost(scores: dict[str, float], graph: dict) -> None:
    """对与 top hit 模块相邻的 chunk 加分（原地修改）。"""
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

        # 1. 精确符号名命中
        if sc.chunk.symbol.lower() in query_terms:
            score += 0.05

        # 2. qualified_name 包含查询词
        qname_lower = sc.chunk.qualified_name.lower()
        if qname_lower and any(t in qname_lower for t in query_terms):
            score += 0.03

        # 3. 多词命中密度（基于可用的文本字段：signature + docstring + qualified_name）
        text_lower = " ".join(
            p
            for p in (
                sc.chunk.signature.lower(),
                (sc.chunk.docstring or "").lower(),
            )
            if p
        )
        hits = sum(1 for t in query_terms if t in text_lower or t in qname_lower)
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


def diversify(
    scored: list[ScoredChunk],
    lambda_diversity: float = 0.15,
) -> list[ScoredChunk]:
    """跨文件多样性折扣——LLM 上下文下避免同一文件的重复片段。

    对来自同一文件的多个 chunk 施加递增折扣，促使排序覆盖更多模块。
    首条不打折；同一文件每多一条，额外扣 ``lambda_diversity``。

    Args:
        scored: 已排序的 chunk
        lambda_diversity: 每次重复的折扣幅度（默认 0.15）
    """
    if len(scored) <= 1:
        return scored

    seen_files: dict[str, int] = {}
    adjusted: list[ScoredChunk] = []

    for sc in scored:
        file = sc.chunk.file_path
        count = seen_files.get(file, 0)
        penalty = lambda_diversity * count
        seen_files[file] = count + 1

        if penalty > 0:
            adjusted.append(
                ScoredChunk(chunk=sc.chunk, score=round(sc.score - penalty, 6))
            )
        else:
            adjusted.append(sc)

    adjusted.sort(key=lambda s: (-s.score, s.chunk.chunk_id))
    return adjusted


def _adjacency(edges: list[dict]) -> dict[str, set[str]]:
    """从 graph edges 构建无向模块邻接表。"""
    adj: dict[str, set[str]] = {}
    for edge in edges:
        src, dst = edge.get("from"), edge.get("to")
        if not src or not dst:
            continue
        adj.setdefault(src, set()).add(dst)
        adj.setdefault(dst, set()).add(src)
    return adj


def load_graph(project_kb_path: Path) -> dict | None:
    """从项目知识库加载 ``_GRAPH.json``（如存在）。"""
    graph_file = project_kb_path / "_GRAPH.json"
    if not graph_file.exists():
        return None
    try:
        return json.loads(graph_file.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return None
