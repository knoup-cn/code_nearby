"""文件系统发现——统一的文件枚举与变更检测。

为 CLI 和 MCP daemon 提供项目源文件发现能力：
- 递归枚举，遵循 .gitignore 与内置忽略规则
- 基于 mtime 的增量变更检测
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

DEFAULT_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".next",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".ace-tool",
    ".agents",
    ".codex",
}

DEFAULT_IGNORE_PATTERNS = {"*.pyc", "*.pyo", "*.so", "*.o", "*.dll", "*.dylib"}


def discover_files(
    project_path: Path,
    *,
    ignore_dirs: set[str] | None = None,
    ignore_patterns: set[str] | None = None,
    gitignore_path: Path | None = None,
) -> list[Path]:
    """枚举项目下所有源文件（递归）。

    自动读取 ``.gitignore``（如果存在）合并排除规则。
    """
    dirs = set(ignore_dirs or DEFAULT_IGNORE_DIRS)
    patterns = set(ignore_patterns or DEFAULT_IGNORE_PATTERNS)

    # 读取 .gitignore
    gi = gitignore_path or project_path / ".gitignore"
    if gi.exists():
        for line in gi.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.add(line)

    files: list[Path] = []
    for root, subdirs, filenames in os.walk(project_path):
        # 原地过滤目录
        subdirs[:] = [d for d in subdirs if d not in dirs and not d.startswith(".")]
        for fname in filenames:
            if any(fnmatch.fnmatch(fname, p) for p in patterns):
                continue
            files.append(Path(root) / fname)
    return files


def detect_changed_files(
    project_path: Path,
    last_index_time: float,
    candidates: list[Path] | None = None,
) -> list[Path]:
    """返回 mtime > *last_index_time* 的文件列表。"""
    files = candidates or discover_files(project_path)
    return [f for f in files if f.stat().st_mtime > last_index_time]
