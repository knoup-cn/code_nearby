"""Tests for graph module — RAG index based."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from code_nearby import graph
from code_nearby.rag.index import RagIndex
from code_nearby.rag.schema import Chunk, compute_content_hash


def _build_test_index(db_path: Path) -> RagIndex:
    """创建含测试数据的 RAG 索引。"""
    index = RagIndex.open(db_path)
    # 插入 module chunks
    index.upsert(
        [
            _make_chunk("module", "src/module1.py", "module1", "", imports="module2"),
            _make_chunk("function", "src/module1.py", "func1", "module1.func1"),
            _make_chunk("module", "src/module2.py", "module2", "", imports="module1"),
            _make_chunk("function", "src/module2.py", "func2", "module2.func2"),
            _make_chunk("module", "src/sub/module3.py", "module3", "", imports="module1\nmodule2"),
            _make_chunk("class", "src/sub/module3.py", "MyClass", "module3.MyClass"),
            _make_chunk("module", "src/module4.py", "module4", "", imports=""),
            _make_chunk("function", "src/module4.py", "_private_func", "module4._private_func"),
        ]
    )
    return index


def _make_chunk(
    chunk_type: str,
    file_path: str,
    symbol: str,
    qualified_name: str,
    *,
    imports: str = "",
    signature: str = "",
    start_line: int = 1,
    content: str = "pass\n",
) -> Chunk:
    """快速构造测试用 Chunk。"""
    return Chunk(
        chunk_id=f"{file_path}::{qualified_name or '<module>'}",
        file_path=file_path,
        language="python",
        chunk_type=chunk_type,
        symbol=symbol,
        qualified_name=qualified_name,
        parent_class=None,
        start_line=start_line,
        end_line=start_line + 1,
        imports=tuple(imports.split("\n")) if imports else (),
        signature=signature,
        docstring=None,
        content=content,
        content_hash=compute_content_hash(content),
    )


def test_generate_graph_basic():
    """测试基本的图生成 — 模块节点、符号节点、边。"""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "index.sqlite3"
        index = _build_test_index(db_path)

        g = graph.generate_graph(index, "test_project")
        index.close()

        # 结构
        assert g["schema_version"] == "v1"
        assert g["project"] == "test_project"
        assert "nodes" in g
        assert "edges" in g
        assert "stats" in g

        # 模块节点
        assert "module1" in g["nodes"]
        assert g["nodes"]["module1"]["type"] == "module"
        assert g["nodes"]["module1"]["source_path"] == "src/module1.py"
        assert g["nodes"]["module1"]["exports"] == ["func1"]

        assert "sub.module3" in g["nodes"]
        assert g["nodes"]["sub.module3"]["exports"] == ["MyClass"]

        # module4 只有私有符号，exports 为空
        assert g["nodes"]["module4"]["exports"] == []

        # 符号节点
        assert "module1.func1" in g["nodes"]
        assert g["nodes"]["module1.func1"]["type"] == "function"
        assert g["nodes"]["module1.func1"]["parent"] == "module1"

        assert "sub.module3.MyClass" in g["nodes"]
        assert g["nodes"]["sub.module3.MyClass"]["type"] == "class"

        # 私有符号
        assert g["nodes"]["module4._private_func"]["is_private"] is True

        # 边：module1 → module2, module2 → module1, module3 → module1, module3 → module2
        assert len(g["edges"]) >= 3

        # 统计
        assert g["stats"]["total_modules"] == 4
        assert g["stats"]["total_symbols"] == 4  # func1, func2, MyClass, _private_func
        assert g["stats"]["total_edges"] >= 3


def test_generate_graph_no_edges_for_empty_imports():
    """导入为空的模块不产生边。"""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "index.sqlite3"
        index = RagIndex.open(db_path)
        index.upsert(
            [
                _make_chunk("module", "src/a.py", "a", "", imports=""),
                _make_chunk("module", "src/b.py", "b", "", imports=""),
            ]
        )

        g = graph.generate_graph(index, "test")
        index.close()

        assert len(g["edges"]) == 0
        assert g["stats"]["total_modules"] == 2


def test_save_graph():
    """测试保存图到 _GRAPH.json。"""
    with TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        test_graph = {
            "schema_version": "v1",
            "project": "test",
            "nodes": {},
            "edges": [],
        }

        graph_file = graph.save_graph(test_graph, kb_path)

        assert graph_file.exists()
        assert graph_file.name == "_GRAPH.json"

        loaded = json.loads(graph_file.read_text())
        assert loaded["schema_version"] == "v1"
        assert loaded["project"] == "test"


def test_resolve_dependency_exact():
    """精确匹配模块名。"""
    names = {"code_nearby.storage", "code_nearby.analyzer", "code_nearby.cli"}
    assert graph._resolve_dependency("code_nearby.storage", names) == "code_nearby.storage"
    assert graph._resolve_dependency("nonexistent", names) is None


def test_resolve_dependency_suffix():
    """后缀匹配模块名。"""
    names = {"code_nearby.storage", "code_nearby.analyzer", "code_nearby.cli"}
    assert graph._resolve_dependency("storage", names) == "code_nearby.storage"
    assert graph._resolve_dependency("analyzer", names) == "code_nearby.analyzer"
    assert graph._resolve_dependency("unknown", names) is None


def test_resolve_dependency_prefers_module_over_symbol():
    """依赖叶子名必须解析为模块，而非同名符号。

    Regression: ``code_nearby.cli`` 定义一个名为 ``context`` 的命令符号
    （节点 ``code_nearby.cli.context``），而 ``code_nearby.context`` 才是真正的
    模块。``[[context]]`` 导入依赖必须解析为模块。
    """
    # _resolve_dependency 只在模块名集合中搜索，所以不会匹配符号
    names = {"code_nearby.cli", "code_nearby.context"}
    assert graph._resolve_dependency("context", names) == "code_nearby.context"


def test_file_path_to_module():
    """文件路径 → 模块名转换。"""
    assert graph._file_path_to_module("src/code_nearby/analyzer.py") == "code_nearby.analyzer"
    assert graph._file_path_to_module("lib/utils/helpers.go") == "utils.helpers"
    assert graph._file_path_to_module("app/components/Button.tsx") == "components.Button"
    assert graph._file_path_to_module("module.py") == "module"
    assert graph._file_path_to_module("pkg/foo/bar.py") == "foo.bar"


def test_import_to_candidate():
    """import 字符串 → 候选模块名。"""
    # Python 点分路径
    assert graph._import_to_candidate("code_nearby.storage") == "code_nearby.storage"
    # 文件路径 → stem
    assert graph._import_to_candidate("./local") == "local"
    assert graph._import_to_candidate("@/utils/helpers") == "helpers"


def test_generate_graph_avoids_duplicate_edges():
    """重复边不会被多次添加。"""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "index.sqlite3"
        index = RagIndex.open(db_path)
        # 两个模块都导入同一个 dep 模块
        index.upsert(
            [
                _make_chunk("module", "src/dep.py", "dep", "", imports=""),
                _make_chunk("module", "src/mod1.py", "mod1", "", imports="dep"),
                _make_chunk("module", "src/mod2.py", "mod2", "", imports="dep"),
            ]
        )

        g = graph.generate_graph(index, "test")
        index.close()

        edges_to_dep = [e for e in g["edges"] if e["to"] == "dep"]
        assert len(edges_to_dep) == 2  # mod1→dep, mod2→dep

        # 无重复
        edge_tuples = [(e["from"], e["to"], e["type"]) for e in g["edges"]]
        assert len(edge_tuples) == len(set(edge_tuples))
