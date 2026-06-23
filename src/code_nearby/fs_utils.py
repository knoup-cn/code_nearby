"""文件系统发现——统一的文件枚举与变更检测。

为 CLI 和 MCP daemon 提供项目源文件发现能力：
- 递归枚举，遵循 .gitignore 与内置忽略规则
- 基于 mtime 的增量变更检测
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import pathspec

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


def _load_gitignore_spec(
    project_path: Path, gitignore_path: Path | None = None
) -> pathspec.PathSpec | None:
    """解析 ``.gitignore``，返回 ``pathspec.PathSpec`` 或 ``None``。"""
    gi = gitignore_path or project_path / ".gitignore"
    if not gi.exists():
        return None
    lines = [
        line.strip()
        for line in gi.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return (
        pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, lines)
        if lines
        else None
    )


def discover_files(
    project_path: Path,
    *,
    ignore_dirs: set[str] | None = None,
    ignore_patterns: set[str] | None = None,
    gitignore_path: Path | None = None,
) -> list[Path]:
    """枚举项目下所有源文件（递归）。

    自动读取 ``.gitignore``（如果存在），使用 ``pathspec`` 做路径级匹配，
    支持 ``**``、否定 (``!``)、目录专用 (``/`` 结尾) 等完整语法。
    """
    dirs = set(ignore_dirs or DEFAULT_IGNORE_DIRS)
    patterns = set(ignore_patterns or DEFAULT_IGNORE_PATTERNS)
    spec = _load_gitignore_spec(project_path, gitignore_path)

    files: list[Path] = []
    for root, subdirs, filenames in os.walk(project_path):
        # 原地修剪子目录：显式忽略 + pathspec 匹配
        kept: list[str] = []
        for d in subdirs:
            if d in dirs:
                continue
            if spec is not None:
                try:
                    rel = str((Path(root) / d).relative_to(project_path))
                except ValueError:
                    rel = d
                if spec.match_file(rel):
                    continue
            kept.append(d)
        subdirs[:] = kept

        for fname in filenames:
            # 内置 basename 级过滤
            if any(fnmatch.fnmatch(fname, p) for p in patterns):
                continue

            file_path = Path(root) / fname
            # .gitignore 路径级过滤（相对于项目根）
            if spec is not None:
                try:
                    file_rel = file_path.relative_to(project_path)
                except ValueError:
                    file_rel = file_path
                if spec.match_file(str(file_rel)):
                    continue

            files.append(file_path)
    return files


def detect_changed_files(
    project_path: Path,
    last_index_time: float,
    candidates: list[Path] | None = None,
) -> list[Path]:
    """返回 mtime > *last_index_time* 的文件列表。"""
    files = candidates or discover_files(project_path)
    return [f for f in files if f.stat().st_mtime > last_index_time]
