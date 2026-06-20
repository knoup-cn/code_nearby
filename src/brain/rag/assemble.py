"""Context assembly: token-budget trim + file:line citations + JSON (C6/C7/C8).

Turns ranked :class:`ScoredChunk` results into a stable JSON payload suitable
to feed a prompt or a skill. Token counting is a dependency-free heuristic
(~4 chars/token); swap in a real tokenizer later if precision matters.
"""

from __future__ import annotations

from typing import Any

from brain.rag.retrieve import ScoredChunk
from brain.rag.schema import Chunk


def estimate_tokens(text: str) -> int:
    """Cheap, dependency-free token estimate (~4 characters per token)."""
    return max(1, (len(text) + 3) // 4)


def chunk_tokens(chunk: Chunk) -> int:
    """Token cost of a chunk *as emitted* — content plus the metadata fields.

    The payload entry carries the file path, qualified name and signature
    alongside the body, so budgeting on ``content`` alone under-counts. This
    estimates the whole entry's textual footprint (slightly conservative, which
    is the safe direction for a hard prompt budget).
    """
    meta = " ".join(
        (chunk.file_path, chunk.qualified_name, chunk.signature, chunk.language, chunk.chunk_type)
    )
    return estimate_tokens(chunk.content) + estimate_tokens(meta)


def assemble(query: str, results: list[ScoredChunk], budget: int | None = None) -> dict[str, Any]:
    """Build the structured retrieval payload, trimming to a token budget.

    Results are assumed pre-ranked (highest score first). Chunks are admitted in
    rank order while they fit; an over-budget chunk is skipped but assembly keeps
    going so a smaller, lower-ranked chunk can still fill the remaining room. The
    top result is always included. ``truncated`` flags that at least one chunk
    was dropped to fit; ``budget=None`` keeps all.
    """
    included: list[ScoredChunk] = []
    total = 0
    truncated = False
    for scored in results:
        cost = chunk_tokens(scored.chunk)
        if budget is not None and included and total + cost > budget:
            truncated = True
            continue  # skip the oversized chunk; a later, smaller one may still fit
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
