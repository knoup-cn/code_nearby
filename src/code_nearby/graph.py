"""依赖图生成——从 RAG 索引构建模块依赖关系图。

从 SQLite chunks 表读取模块、符号和 import 信息，构建带节点和边的
依赖图，保存为 ``_GRAPH.json``。供检索时做依赖邻近度加分（graph boost）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from code_nearby.rag.index import RagIndex


def generate_graph(index: RagIndex, project_name: str) -> dict[str, Any]:
    """从 RAG 索引构建依赖图。

    读取 chunks 表中的 module / function / class 记录，组装：
    - 模块节点（含 source_path、exports、行数）
    - 符号节点（函数/类，含签名、位置提示）
    - import 边（模块间的依赖关系）

    Args:
        index: RAG 索引实例
        project_name: 项目名称

    Returns:
        包含 nodes、edges、stats 的图字典
    """
    graph: dict[str, Any] = {
        "schema_version": "v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "project": project_name,
        "nodes": {},
        "edges": [],
    }

    conn = index._conn

    # 第一遍：module chunk → 模块节点
    module_rows = conn.execute(
        "SELECT file_path, language, imports, start_line, end_line "
        "FROM chunks WHERE chunk_type = 'module'"
    ).fetchall()

    for row in module_rows:
        module_name = _file_path_to_module(row["file_path"])
        graph["nodes"][module_name] = {
            "type": "module",
            "md_path": "",
            "source_path": row["file_path"],
            "exports": [],
            "lines_of_code": row["end_line"] - row["start_line"] + 1,
        }

    # 第二遍：function / class chunk → 符号节点 + 填充模块 exports
    symbol_rows = conn.execute(
        "SELECT file_path, chunk_type, symbol, qualified_name, "
        "signature, start_line FROM chunks "
        "WHERE chunk_type IN ('function', 'class')"
    ).fetchall()

    for row in symbol_rows:
        module_name = _file_path_to_module(row["file_path"])
        if module_name not in graph["nodes"]:
            continue

        symbol_full = f"{module_name}.{row['symbol']}"
        is_private = row["symbol"].startswith("_")
        node: dict[str, Any] = {
            "type": row["chunk_type"],
            "parent": module_name,
            "signature": row["signature"],
            "location_hint": row["start_line"],
            "is_private": is_private,
        }
        graph["nodes"][symbol_full] = node

        if not is_private:
            graph["nodes"][module_name]["exports"].append(row["symbol"])

    # 第三遍：从模块 imports 构建边
    module_names = {name for name, node in graph["nodes"].items() if node.get("type") == "module"}

    for row in module_rows:
        module_name = _file_path_to_module(row["file_path"])
        imports_raw = row["imports"] or "[]"
        for imp in json.loads(imports_raw):
            dep_module = _resolve_import(imp, module_names)
            if dep_module and dep_module != module_name:
                edge = {
                    "from": module_name,
                    "to": dep_module,
                    "type": "imports",
                    "metadata": {},
                }
                if edge not in graph["edges"]:
                    graph["edges"].append(edge)

    # 统计
    graph["stats"] = {
        "total_modules": sum(1 for n in graph["nodes"].values() if n["type"] == "module"),
        "total_symbols": sum(
            1 for n in graph["nodes"].values() if n["type"] in ("function", "class")
        ),
        "total_edges": len(graph["edges"]),
    }

    return graph


def save_graph(graph: dict[str, Any], kb_path: Path) -> Path:
    """保存图到 _GRAPH.json。

    Args:
        graph: 图字典
        kb_path: 知识库根路径

    Returns:
        保存的图文件路径
    """
    graph_file = kb_path / "_GRAPH.json"
    graph_file.write_text(json.dumps(graph, indent=2))
    return graph_file


# ======================================================================
# 辅助函数
# ======================================================================


def _file_path_to_module(file_path: str) -> str:
    """将仓库相对路径转换为点分模块名。

    ``src/code_nearby/analyzer.py`` → ``code_nearby.analyzer``
    ``lib/utils/helpers.go`` → ``utils.helpers``
    ``app/components/Button.tsx`` → ``components.Button``
    """
    path = Path(file_path)
    parts = [*list(path.parts[:-1]), path.stem]
    if parts and parts[0] in ("src", "lib", "app", "pkg"):
        parts = parts[1:]
    return ".".join(parts)


def _resolve_dependency(dep_name: str, module_names: set[str]) -> str | None:
    """将依赖名解析为完整模块名。

    Import 依赖始终指向模块，因此解析限定在模块节点范围内。
    这防止了与恰好共享依赖叶子名的符号冲突（例如 CLI 命令 ``context``
    和 ``code_nearby.context`` 模块）。

    Args:
        dep_name: 依赖名（如 "storage" 或 "code_nearby.storage"）
        module_names: 图中所有模块名的集合

    Returns:
        完整模块名（如 "code_nearby.storage"）或 None
    """
    # 精确匹配优先
    if dep_name in module_names:
        return dep_name

    # 后缀匹配（按字母序，结果确定）
    candidates = sorted(name for name in module_names if name.endswith(f".{dep_name}"))
    return candidates[0] if candidates else None


def _import_to_candidate(imp: str) -> str:
    """将 import 字符串转换为候选模块名。

    Python 点分路径直接返回；文件路径提取 stem 作为短名。
    """
    if "/" in imp or "\\" in imp:
        return Path(imp).stem
    return imp


def _resolve_import(imp: str, module_names: set[str]) -> str | None:
    """将一条 import 解析为图中的模块名。外部依赖返回 None。"""
    return _resolve_dependency(_import_to_candidate(imp), module_names)
