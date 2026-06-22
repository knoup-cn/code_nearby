"""Brain — 代码分析与本地 RAG context engine。

提供两个核心函数：

- :func:`analyze` — 分析源码仓库，产出 RAG 检索索引 + 依赖图
- :func:`search` — 检索 RAG 索引，返回结构化代码片段

Usage::

    import brain
    brain.analyze("/path/to/project")
    results = brain.search("verify token", max_results=3)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["__version__", "analyze", "search"]
__version__ = "0.1.0"


def analyze(project_path: str | Path = ".", *, full: bool = False) -> dict[str, Any]:
    """分析源码仓库，产出 RAG 索引 + 依赖图。

    这是程序化入口，等价于 CLI 的 ``brain analyze .``。

    Args:
        project_path: 源 Git 仓库路径，默认当前目录。
        full: 是否强制全量重建（默认增量）。

    Returns:
        {
            "success": bool,
            "files_analyzed": int,
            "added": int, "modified": int, "deleted": int,
            "chunks_total": int,
            "kb_path": str | None,
            "error": str | None,
        }

    Raises:
        FileNotFoundError: project_path 不存在。
        RuntimeError: 知识库未初始化。
    """
    from brain.operations.analysis import run_full_analysis
    from brain.operations.config import get_status

    target = Path(project_path).resolve()
    if not target.exists():
        raise FileNotFoundError(f"Project path does not exist: {target}")
    if not get_status():
        raise RuntimeError("Knowledge base not initialized. Run 'brain init' first.")
    return run_full_analysis(target, full_rebuild=full)


def search(
    query: str,
    project_path: str | Path = ".",
    *,
    max_results: int = 5,
    language: str | None = None,
    path_glob: str | None = None,
    budget: int | None = None,
) -> dict[str, Any]:
    """检索 RAG 索引，返回 token 预算感知的结构化代码片段。

    Args:
        query: 自然语言或标识符查询。
        project_path: 项目路径，默认当前目录。
        max_results: 最大返回结果数。
        language: 按语言过滤（如 ``"python"``）。
        path_glob: 按文件路径 glob 过滤（如 ``"src/**/*.py"``）。
        budget: token 预算上限（None = 不限制）。

    Returns:
        {
            "query": str,
            "truncated": bool,
            "token_estimate": int,
            "results": [
                {
                    "rank": int, "score": float,
                    "file": str, "lines": str, "ref": str,
                    "language": str, "type": str,
                    "qualified_name": str, "signature": str,
                    "content": str,
                }, ...
            ],
        }

    Raises:
        RuntimeError: 知识库或搜索索引未初始化。
    """
    from brain import storage
    from brain.operations.config import get_status
    from brain.rag import assemble, retrieve
    from brain.rag.index import RagIndex

    cfg = get_status()
    if not cfg:
        raise RuntimeError("Knowledge base not initialized. Run 'brain init' first.")

    kb_path = Path(cfg["local_path"])
    target = Path(project_path).resolve()
    project_kb_path = storage.get_project_kb_path(kb_path, target)
    index_file = project_kb_path / ".rag" / "index.sqlite3" if project_kb_path else None

    if index_file is None or not index_file.exists():
        raise RuntimeError(
            f"No search index for project: {target.name}. "
            "Run brain.analyze() or 'brain analyze' first."
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
        return assemble.assemble(query, scored, budget=budget)
    finally:
        idx.close()
