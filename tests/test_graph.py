"""Tests for graph module."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from brain import graph


def test_generate_graph_basic():
    """Test basic graph generation."""
    with TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # Create test Markdown files
        (kb_path / "module1.md").write_text(
            """---
brain_schema: "v1"
type: module
source_path: src/module1.py
module: brain.module1
exports:
  - func1
symbols:
  - name: func1
    type: function
    signature: "def func1() -> None:"
    signature_hash: "abc12345"
    location_hint: 10
    is_private: false
    is_async: false
---

# module1
"""
        )

        (kb_path / "module2.md").write_text(
            """---
brain_schema: "v1"
type: module
source_path: src/module2.py
module: brain.module2
exports:
  - func2
dependencies:
  - "[[module1]]"
symbols:
  - name: func2
    type: function
    signature: "def func2() -> None:"
    signature_hash: "def67890"
    location_hint: 5
    is_private: false
    is_async: false
---

# module2
"""
        )

        # Generate graph
        g = graph.generate_graph(kb_path, "brain")

        # Check basic structure
        assert g["schema_version"] == "v1"
        assert g["project"] == "brain"
        assert "nodes" in g
        assert "edges" in g
        assert "stats" in g

        # Check nodes
        assert "brain.module1" in g["nodes"]
        assert "brain.module2" in g["nodes"]
        assert "brain.module1.func1" in g["nodes"]
        assert "brain.module2.func2" in g["nodes"]

        # Check module node structure
        mod1 = g["nodes"]["brain.module1"]
        assert mod1["type"] == "module"
        assert mod1["source_path"] == "src/module1.py"
        assert mod1["exports"] == ["func1"]

        # Check symbol node structure
        func1 = g["nodes"]["brain.module1.func1"]
        assert func1["type"] == "function"
        assert func1["parent"] == "brain.module1"
        assert func1["signature_hash"] == "abc12345"
        assert func1["location_hint"] == 10
        assert func1["is_private"] is False
        assert func1["is_async"] is False

        # Check edges
        assert len(g["edges"]) > 0
        import_edge = [e for e in g["edges"] if e["type"] == "imports"][0]
        assert import_edge["from"] == "brain.module2"
        assert import_edge["to"] == "brain.module1"

        # Check stats
        assert g["stats"]["total_modules"] == 2
        assert g["stats"]["total_symbols"] == 2
        assert g["stats"]["total_edges"] >= 1


def test_generate_graph_with_classes():
    """Test graph generation with classes."""
    with TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        (kb_path / "module.md").write_text(
            """---
brain_schema: "v1"
type: module
source_path: src/module.py
module: brain.module
exports:
  - MyClass
symbols:
  - name: MyClass
    type: class
    signature: "class MyClass:"
    signature_hash: "class123"
    location_hint: 5
    is_private: false
---

# module
"""
        )

        g = graph.generate_graph(kb_path, "brain")

        # Check class node
        assert "brain.module.MyClass" in g["nodes"]
        cls = g["nodes"]["brain.module.MyClass"]
        assert cls["type"] == "class"
        assert cls["parent"] == "brain.module"
        assert "is_async" not in cls  # Classes don't have is_async


def test_parse_frontmatter():
    """Test frontmatter parsing."""
    content = """---
brain_schema: "v1"
module: test.module
---

# content
"""
    fm = graph._parse_frontmatter(content)
    assert fm is not None
    assert fm["brain_schema"] == "v1"
    assert fm["module"] == "test.module"


def test_parse_frontmatter_invalid():
    """Test invalid frontmatter."""
    # No frontmatter
    assert graph._parse_frontmatter("# No frontmatter") is None

    # Invalid YAML
    assert graph._parse_frontmatter("---\ninvalid: [yaml\n---") is None


def test_resolve_dependency():
    """Test dependency resolution."""
    nodes = {
        "brain.storage": {"type": "module"},
        "brain.analyzer": {"type": "module"},
        "brain.storage.save": {"type": "function"},
    }

    # Exact match
    assert graph._resolve_dependency("brain.storage", nodes) == "brain.storage"

    # Suffix match
    assert graph._resolve_dependency("storage", nodes) == "brain.storage"
    assert graph._resolve_dependency("analyzer", nodes) == "brain.analyzer"

    # Not found
    assert graph._resolve_dependency("unknown", nodes) is None


def test_resolve_dependency_prefers_module_over_symbol():
    """A dependency leaf name must resolve to a module, not a symbol sharing the name.

    Regression: ``brain.cli`` defines a command symbol ``context`` (node
    ``brain.cli.context``) while ``brain.context`` is a real module. A ``[[context]]``
    import dependency must resolve to the module, not the colliding symbol.
    """
    nodes = {
        "brain.cli": {"type": "module"},
        "brain.cli.context": {"type": "function"},
        "brain.context": {"type": "module"},
    }
    assert graph._resolve_dependency("context", nodes) == "brain.context"


def test_save_graph():
    """Test saving graph to file."""
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

        # Verify content
        loaded = json.loads(graph_file.read_text())
        assert loaded["schema_version"] == "v1"
        assert loaded["project"] == "test"


def test_generate_graph_skips_index_files():
    """Test that files starting with _ are skipped."""
    with TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # Create index file (should be skipped)
        (kb_path / "_PROJECT.md").write_text(
            """---
brain_schema: "v1"
module: _PROJECT
---
"""
        )

        # Create normal file
        (kb_path / "module.md").write_text(
            """---
brain_schema: "v1"
type: module
source_path: src/module.py
module: brain.module
exports: []
symbols: []
---
"""
        )

        g = graph.generate_graph(kb_path, "brain")

        # Only the normal module should be in the graph
        assert "brain.module" in g["nodes"]
        assert "_PROJECT" not in g["nodes"]
        assert g["stats"]["total_modules"] == 1


def test_generate_graph_avoids_duplicate_edges():
    """Test that duplicate edges are not added."""
    with TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # Create two files that both depend on the same module
        (kb_path / "dep.md").write_text(
            """---
brain_schema: "v1"
module: brain.dep
exports: []
symbols: []
---
"""
        )

        (kb_path / "module1.md").write_text(
            """---
brain_schema: "v1"
module: brain.module1
dependencies:
  - "[[dep]]"
exports: []
symbols: []
---
"""
        )

        (kb_path / "module2.md").write_text(
            """---
brain_schema: "v1"
module: brain.module2
dependencies:
  - "[[dep]]"
exports: []
symbols: []
---
"""
        )

        g = graph.generate_graph(kb_path, "brain")

        # Each module should have only one edge to dep
        edges_to_dep = [e for e in g["edges"] if e["to"] == "brain.dep"]
        assert len(edges_to_dep) == 2  # One from module1, one from module2

        # No duplicate edges
        edge_tuples = [(e["from"], e["to"], e["type"]) for e in g["edges"]]
        assert len(edge_tuples) == len(set(edge_tuples))
