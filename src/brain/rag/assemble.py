"""Context assembly: token-budget trim + file:line citations + JSON (C6/C7/C8).

Turns ranked :class:`ScoredChunk` results into a stable JSON payload suitable
to feed a prompt or a skill. Token counting is a dependency-free heuristic
(~4 chars/token); swap in a real tokenizer later if precision matters.
"""

from __future__ import annotations

from typing import Any

from brain.rag.retrieve import ScoredChunk


def estimate_tokens(text: str) -> int:
    """Cheap, dependency-free token estimate (~4 characters per token)."""
    return max(1, (len(text) + 3) // 4)


def assemble(query: str, results: list[ScoredChunk], budget: int | None = None) -> dict[str, Any]:
    """Build the structured retrieval payload, trimming to a token budget.

    Results are assumed pre-ranked. Chunks are included greedily until the next
    would exceed ``budget`` (the top result is always included); ``truncated``
    flags that lower-ranked chunks were dropped. ``budget=None`` keeps all.
    """
    included: list[ScoredChunk] = []
    total = 0
    truncated = False
    for scored in results:
        cost = estimate_tokens(scored.chunk.content)
        if budget is not None and included and total + cost > budget:
            truncated = True
            break
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
