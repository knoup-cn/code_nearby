"""Source Fetch — 从磁盘按位置读取源码，支持窗口扩展。

Index 是地图，不是仓库。检索命中后从此模块从磁盘获取最新源码。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

WINDOW_PRESETS: dict[str, tuple[int, int]] = {
    "none": (0, 0),
    "minimal": (2, 2),
    "moderate": (5, 5),
    "generous": (10, 10),
}


@dataclass(frozen=True, slots=True)
class SourceSnippet:
    """从磁盘读取的源码片段。"""

    file_path: str
    start_line: int  # 1-indexed，含窗口扩展
    end_line: int
    content: str  # 实际源码文本
    original_start: int  # 命中 chunk 的原始起始行（不含扩展）
    original_end: int  # 命中 chunk 的原始结束行


def fetch_source(
    project_root: Path,
    file_path: str,
    start_line: int,
    end_line: int,
    *,
    context_before: int = 0,
    context_after: int = 0,
) -> SourceSnippet | None:
    """从磁盘读取源文件的行范围。

    读取失败（文件不存在/权限错误/编码错误）返回 None。
    context_before/after 用于窗口扩展——不会超出文件边界。
    """
    full_path = project_root / file_path
    try:
        lines = full_path.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        return None

    total = len(lines)
    actual_start = max(1, start_line - context_before)
    actual_end = min(total, end_line + context_after)

    snippet = "\n".join(lines[actual_start - 1 : actual_end])
    return SourceSnippet(
        file_path=file_path,
        start_line=actual_start,
        end_line=actual_end,
        content=snippet,
        original_start=start_line,
        original_end=end_line,
    )


def expand_window_params(strategy: str) -> tuple[int, int]:
    """将策略名映射为 (context_before, context_after)。"""
    strategy_lower = strategy.lower()
    if strategy_lower in WINDOW_PRESETS:
        return WINDOW_PRESETS[strategy_lower]
    # 解析 "N,M" 格式的自定义窗口
    if "," in strategy_lower:
        parts = strategy_lower.split(",", 1)
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            pass
    return WINDOW_PRESETS["moderate"]


# --- batch fetch -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RangeRequest:
    """单个文件的区间请求，用于批量去重读取。"""

    index: int  # 调用方的原始顺序索引
    start_line: int
    end_line: int
    context_before: int
    context_after: int


def batch_fetch_sources(
    project_root: Path,
    requests: list[tuple[str, int, int, int, int]],
) -> list[SourceSnippet | None]:
    """批量读取多个源码区间，消除同一文件的重复 IO。

    Args:
        project_root: 项目根目录
        requests: ``[(file_path, start_line, end_line, context_before, context_after), ...]``

    Returns:
        与 requests 等长的 SourceSnippet 列表（失败项为 None），保持输入顺序
    """
    if not requests:
        return []

    # 按 file_path 分组，保留原始索引
    groups: dict[str, list[_RangeRequest]] = {}
    for idx, (fp, sl, el, cb, ca) in enumerate(requests):
        req = _RangeRequest(idx, sl, el, cb, ca)
        groups.setdefault(fp, []).append(req)

    results: list[SourceSnippet | None] = [None] * len(requests)

    for file_path, reqs in groups.items():
        full_path = project_root / file_path
        try:
            lines = full_path.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            continue  # 该文件所有请求保持 None

        total = len(lines)
        for req in reqs:
            actual_start = max(1, req.start_line - req.context_before)
            actual_end = min(total, req.end_line + req.context_after)
            if actual_start > total:
                results[req.index] = SourceSnippet(
                    file_path=file_path,
                    start_line=actual_start,
                    end_line=actual_end,
                    content="",
                    original_start=req.start_line,
                    original_end=req.end_line,
                )
                continue
            snippet = "\n".join(lines[actual_start - 1 : actual_end])
            results[req.index] = SourceSnippet(
                file_path=file_path,
                start_line=actual_start,
                end_line=actual_end,
                content=snippet,
                original_start=req.start_line,
                original_end=req.end_line,
            )

    return results
