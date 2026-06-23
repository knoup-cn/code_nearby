"""Code Nearby — MCP server for codebase context.

Primary interface is MCP (``nearby-mcp``). The ``analyze`` and ``search``
functions below are the programmatic API for library usage and testing.

Usage::

    import code_nearby
    code_nearby.analyze("/path/to/project")
    results = code_nearby.search("verify token", max_results=3)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["__version__", "analyze", "search"]
__version__ = "0.1.0"


def analyze(project_path: str | Path = ".", *, full: bool = False) -> dict[str, Any]:
    """分析源码仓库，产出 RAG 索引 + 依赖图。

    Args:
        project_path: 源项目路径，默认当前目录。
        full: 是否强制全量重建（默认增量）。

    Returns:
        {
            "success": bool,
            "files_analyzed": int,
            "added": int, "modified": int, "deleted": int,
            "chunks_added": int, "chunks_updated": int, "chunks_deleted": int,
            "chunks_total": int,
            "kb_path": str | None,
            "error": str | None,
        }
    """
    from code_nearby.operations.analysis import run_full_analysis

    target = Path(project_path).resolve()
    if not target.exists():
        raise FileNotFoundError(f"Project path does not exist: {target}")
    return run_full_analysis(target, full_rebuild=full)


def search(
    query: str,
    project_path: str | Path = ".",
    *,
    max_results: int = 5,
    language: str | None = None,
    path_glob: str | None = None,
    budget: int | None = None,
    window_strategy: str = "moderate",
) -> dict[str, Any]:
    """检索 RAG 索引，返回结构化代码片段。

    Args:
        query: 自然语言或标识符查询。
        project_path: 项目路径，默认当前目录。
        max_results: 最大返回结果数。
        language: 按语言过滤。
        path_glob: 按文件路径 glob 过滤。
        budget: token 预算上限。
        window_strategy: 上下文窗口策略。

    Raises:
        RuntimeError: 搜索索引未初始化。
    """
    from code_nearby import config, storage
    from code_nearby.rag import assemble, retrieve
    from code_nearby.rag.index import RagIndex

    kb_path = config.get_kb_path()
    target = Path(project_path).resolve()
    project_kb_path = storage.get_project_kb_path(kb_path, target)
    index_file = project_kb_path / ".rag" / "index.sqlite3" if project_kb_path else None

    if index_file is None or not index_file.exists():
        raise RuntimeError(
            f"No search index for project: {target.name}. "
            "Run code_nearby.analyze() or connect the MCP server first."
        )

    idx = RagIndex.open(index_file)
    try:
        scored = retrieve.search(
            idx,
            query,
            k=max_results,
            language=language,
            path_glob=path_glob,
            graph=retrieve.load_graph(project_kb_path) if project_kb_path else None,
        )
        return assemble.assemble(
            query,
            scored,
            budget=budget,
            project_root=target,
            window_strategy=window_strategy,
        )
    finally:
        idx.close()
