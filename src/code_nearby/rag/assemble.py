"""上下文拼装：token 预算裁剪 + file:line 引用 + JSON。

将排序后的 :class:`ScoredChunk` 结果转为稳定的 JSON 结构，
可直接喂给 prompt 或 skill。token 估算优先使用 tiktoken（精确），
回退到 CJK 感知启发式。

当 ``project_root`` 传入时，通过 Source Fetch 从磁盘读取最新源码；
否则回退到 chunk.content（测试兼容模式）。
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from code_nearby.rag.retrieve import ScoredChunk
    from code_nearby.rag.schema import Chunk

from code_nearby.rag.source_fetch import (
    SourceSnippet,
    batch_fetch_sources,
    expand_window_params,
)

# --- token estimation ---------------------------------------------------------

# 延迟导入 tiktoken——可选依赖，仅在精确估算时需要
_tiktoken_enc: object = None


def _get_tiktoken_enc() -> object | None:
    """惰性加载 cl100k_base 编码器（ChatGPT/Claude 共用词汇表）。"""
    global _tiktoken_enc
    if _tiktoken_enc is None:
        try:
            import tiktoken

            _tiktoken_enc = tiktoken.get_encoding("cl100k_base")
        except (ImportError, Exception):
            _tiktoken_enc = False  # sentinel：不可用
    return _tiktoken_enc if _tiktoken_enc is not False else None


def estimate_tokens(text: str) -> int:
    """Token 估算：优先 tiktoken，回退 CJK 感知启发式。

    精确模式（tiktoken 可用）使用 cl100k_base 编码器直接计数。
    回退启发式按 Unicode 类别分段计数——CJK 字符 ~1.5 token/字，
    ASCII 字符 ~0.25 token/字——比 ``len/4`` 的 CJK 误差好约 3×。
    """
    enc = _get_tiktoken_enc()
    if enc is not None:
        return len(enc.encode(text))  # type: ignore[attr-defined]

    # 回退：CJK 感知启发式
    cjk_chars = ascii_chars = 0
    for ch in text:
        cat = unicodedata.category(ch)
        # CJK Unified Ideographs + Extensions
        if (cat == "Lo" and "一" <= ch <= "鿿") or (cat == "Lo" and (
            "㐀" <= ch <= "䶿"
            or "豈" <= ch <= "﫿"
            or "\U00020000" <= ch <= "\U0002A6DF"
        )):
            cjk_chars += 1
        elif ord(ch) > 127:
            cjk_chars += 1  # 其他非 ASCII（日韩、emoji 等）
        else:
            ascii_chars += 1
    # ~1.5 token per CJK char, ~0.25 token per ASCII char
    return max(1, int(cjk_chars * 1.5 + ascii_chars * 0.25))


def chunk_tokens(chunk: Chunk, *, content: str | None = None) -> int:
    """chunk *输出时*的 token 开销——内容加上元数据字段。

    输出条目包含 file_path、qualified_name、signature 等字段，
    仅按 ``content`` 预算会低估。此函数估算整个条目的文本占用量。

    ``content`` 覆盖 chunk.content 用于 Source Fetch 路径下的准确估算。
    """
    meta = " ".join(
        (chunk.file_path, chunk.qualified_name, chunk.signature, chunk.language, chunk.chunk_type)
    )
    actual_content = content if content is not None else chunk.content
    return estimate_tokens(actual_content) + estimate_tokens(meta)


def assemble(
    query: str,
    results: list[ScoredChunk],
    budget: int | None = None,
    *,
    project_root: Path | None = None,
    window_strategy: str = "moderate",
) -> dict[str, Any]:
    """构建结构化检索结果，按 token 预算裁剪。

    结果假定已排好序（分数从高到低）。按排序依次纳入 chunk，
    直到超出预算；超预算的 chunk 跳过，但后续更小的低排名 chunk
    仍可填补剩余空间。所有 chunk 平等受 budget 约束。
    ``truncated`` 标记是否有 chunk 因预算被丢弃；
    ``budget=None`` 表示不限制。

    ``project_root`` 传入时通过 Source Fetch 从磁盘读取源码；
    否则回退到 chunk.content（测试兼容）。
    ``window_strategy`` 控制上下文窗口扩展量。
    """
    skipped = 0
    included: list[tuple[ScoredChunk, str, str, SourceSnippet | None]] = []
    total = 0
    truncated = False

    context_before, context_after = (
        expand_window_params(window_strategy) if project_root else (0, 0)
    )

    # --- Source Fetch（批量，消除同一文件的重复 IO）---
    snippets: list[SourceSnippet | None]
    if project_root:
        requests = [
            (c.chunk.file_path, c.chunk.start_line, c.chunk.end_line, context_before, context_after)
            for c in results
        ]
        snippets = batch_fetch_sources(project_root, requests)
    else:
        snippets = [None] * len(results)

    for scored, snippet in zip(results, snippets, strict=True):
        chunk = scored.chunk

        if project_root:
            if snippet is None:
                skipped += 1
                continue
            actual_content = snippet.content
            actual_lines = f"{snippet.start_line}-{snippet.end_line}"
        else:
            actual_content = chunk.content
            actual_lines = f"{chunk.start_line}-{chunk.end_line}"

        cost = chunk_tokens(chunk, content=actual_content)
        if budget is not None and total + cost > budget:
            truncated = True
            continue
        included.append((scored, actual_content, actual_lines, snippet))
        total += cost

    payload: dict[str, Any] = {
        "query": query,
        "truncated": truncated,
        "token_estimate": total,
        "results": [
            _entry(i, s, content, lines, snip, window_strategy)
            for i, (s, content, lines, snip) in enumerate(included, start=1)
        ],
    }
    if skipped:
        payload["skipped"] = skipped
    return payload


def _entry(
    rank: int,
    scored: ScoredChunk,
    content: str,
    lines: str,
    snippet: SourceSnippet | None,
    window_strategy: str,
) -> dict[str, Any]:
    chunk = scored.chunk
    entry: dict[str, Any] = {
        "rank": rank,
        "score": scored.score,
        "file": chunk.file_path,
        "lines": lines,
        "ref": (
            f"{chunk.file_path}:{snippet.original_start}"
            if snippet
            else f"{chunk.file_path}:{chunk.start_line}"
        ),
        "language": chunk.language,
        "type": chunk.chunk_type,
        "qualified_name": chunk.qualified_name,
        "signature": chunk.signature,
        "content": content,
    }
    if snippet:
        entry["context_window"] = window_strategy
    return entry
