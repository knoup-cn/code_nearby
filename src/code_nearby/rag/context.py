"""图上下文扩展——利用 _GRAPH.json 为检索结果补充依赖模块上下文。

LLM 理解代码时需要的不仅是命中函数，还包括它依赖的模块签名。
本模块在只读侧使用现有的依赖图，无新增索引。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from code_nearby.rag.index import RagIndex
    from code_nearby.rag.schema import Chunk

# 每个依赖模块最多带回的符号数
_MAX_NEIGHBOR_SYMBOLS = 3


def expand_module_context(
    chunk: Chunk,
    graph: dict[str, Any],
    index: RagIndex,
    *,
    max_symbols: int = _MAX_NEIGHBOR_SYMBOLS,
) -> list[Chunk]:
    """返回 chunk 所在模块的依赖模块中的代表符号。

    从 _GRAPH.json 的 edges 中找出直接依赖（模块 → import 的目标），
    对每个依赖模块返回最多 ``max_symbols`` 个顶层导出符号，
    作为 LLM 上下文的补充。

    Args:
        chunk: 命中的 chunk（含 file_path，用于定位模块）
        graph: 完整依赖图（``load_graph()`` 返回值）
        index: RAG 索引实例
        max_symbols: 每个依赖模块最多带回的符号数

    Returns:
        依赖模块的代表符号列表（不含 chunk 自身所在模块）
    """
    module_by_source = {
        node["source_path"]: name
        for name, node in graph.get("nodes", {}).items()
        if node.get("type") == "module" and node.get("source_path")
    }
    current_module = module_by_source.get(chunk.file_path)
    if current_module is None:
        return []

    # 找出当前模块的依赖模块
    neighbors: set[str] = set()
    for edge in graph.get("edges", []):
        src, dst = edge.get("from"), edge.get("to")
        if src == current_module and dst and dst != current_module:
            neighbors.add(dst)
        elif dst == current_module and src and src != current_module:
            neighbors.add(src)

    if not neighbors:
        return []

    # 对每个依赖模块，取前 N 个导出符号的 chunk
    result: list[Chunk] = []
    for neighbor_name in neighbors:
        neighbor_node = graph["nodes"].get(neighbor_name, {})
        if neighbor_node.get("type") != "module":
            continue
        exports = neighbor_node.get("exports", [])[:max_symbols]
        if not exports:
            continue
        # chunk_id 格式：source_path::qualified_name
        source_path = neighbor_node.get("source_path", "")
        for symbol in exports:
            qname = f"{neighbor_name}.{symbol}"
            chunk_id = f"{source_path}::{qname}"
            chunks = index.get_chunks([chunk_id])
            if chunks:
                result.append(chunks[0])

    return result


def graph_module_name(graph: dict[str, Any], file_path: str) -> str | None:
    """从图中按 source_path 查找模块名。"""
    for name, node in graph.get("nodes", {}).items():
        if node.get("type") == "module" and node.get("source_path") == file_path:
            return name  # type: ignore[no-any-return]
    return None


def load_context_graph(kb_path: Path) -> dict[str, Any] | None:
    """加载 _GRAPH.json 用于上下文扩展（与 retrieve.load_graph 同源）。"""
    graph_file = kb_path / "_GRAPH.json"
    if not graph_file.exists():
        return None
    import json

    try:
        return json.loads(graph_file.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return None
