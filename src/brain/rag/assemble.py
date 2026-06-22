"""上下文拼装：token 预算裁剪 + file:line 引用 + JSON。

将排序后的 :class:`ScoredChunk` 结果转为稳定的 JSON 结构，
可直接喂给 prompt 或 skill。token 计数为无依赖启发式（~4 字符/token）。
"""

from __future__ import annotations

from typing import Any

from brain.rag.retrieve import ScoredChunk
from brain.rag.schema import Chunk


def estimate_tokens(text: str) -> int:
    """廉价的无依赖 token 估算（~4 字符/token）。"""
    return max(1, (len(text) + 3) // 4)


def chunk_tokens(chunk: Chunk) -> int:
    """chunk *输出时*的 token 开销——内容加上元数据字段。

    输出条目包含 file_path、qualified_name、signature 等字段，
    仅按 ``content`` 预算会低估。此函数估算整个条目的文本占用量。
    """
    meta = " ".join(
        (chunk.file_path, chunk.qualified_name, chunk.signature, chunk.language, chunk.chunk_type)
    )
    return estimate_tokens(chunk.content) + estimate_tokens(meta)


def assemble(query: str, results: list[ScoredChunk], budget: int | None = None) -> dict[str, Any]:
    """构建结构化检索结果，按 token 预算裁剪。

    结果假定已排好序（分数从高到低）。按排序依次纳入 chunk，
    直到超出预算；超预算的 chunk 跳过，但后续更小的低排名 chunk
    仍可填补剩余空间。首条结果始终保留。
    ``truncated`` 标记是否有 chunk 因预算被丢弃；
    ``budget=None`` 表示不限制。
    """
    included: list[ScoredChunk] = []
    total = 0
    truncated = False
    for scored in results:
        cost = chunk_tokens(scored.chunk)
        if budget is not None and included and total + cost > budget:
            truncated = True
            continue
        included.append(scored)
        total += cost

    return {
        "query": query,
        "truncated": truncated,
        "token_estimate": total,
        "results": [_entry(i, s) for i, s in enumerate(included, start=1)],
    }


def _entry(rank: int, scored: ScoredChunk) -> dict[str, Any]:
    chunk = scored.chunk
    return {
        "rank": rank,
        "score": scored.score,
        "file": chunk.file_path,
        "lines": f"{chunk.start_line}-{chunk.end_line}",
        "ref": f"{chunk.file_path}:{chunk.start_line}",
        "language": chunk.language,
        "type": chunk.chunk_type,
        "qualified_name": chunk.qualified_name,
        "signature": chunk.signature,
        "content": chunk.content,
    }
