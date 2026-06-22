"""依赖图生成。

生成 ``_GRAPH.json`` 文件，包含模块和符号之间的节点-边关系图。
"""

from __future__ import annotations

from pathlib import Path

from brain import graph
from brain.rag.index import RagIndex


def generate_project_graph(kb_path: Path, project_path: Path) -> None:
    """生成依赖图（_GRAPH.json）。

    从 RAG 索引读取模块和符号信息，构建节点-边图并保存。

    Args:
        kb_path: 项目知识库路径（org/project/）
        project_path: 源项目路径
    """
    project_name = project_path.resolve().name
    rag_dir = kb_path / ".rag"
    index_file = rag_dir / "index.sqlite3"

    if not index_file.exists():
        import sys

        print(
            f"Warning: No RAG index found at {index_file}, skipping graph generation.",
            file=sys.stderr,
        )
        return

    try:
        index = RagIndex.open(index_file)
        try:
            g = graph.generate_graph(index, project_name)
            graph.save_graph(g, kb_path)
        finally:
            index.close()
    except Exception as e:
        import sys

        print(f"Warning: Failed to generate graph: {e}", file=sys.stderr)
