"""Tests for context module."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from brain import context


def test_search_context_exact_match():
    """Test exact module name match."""
    with TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # Create graph
        graph = {
            "schema_version": "v1",
            "project": "test",
            "nodes": {
                "test.module1": {
                    "type": "module",
                    "md_path": "kb/module1.md",
                    "source_path": "src/module1.py",
                    "exports": ["func1"],
                },
            },
            "edges": [],
            "stats": {},
        }
        (kb_path / "_GRAPH.json").write_text(json.dumps(graph))

        # Create markdown
        (kb_path / "module1.md").write_text(
            """---
brain_schema: "v1"
module: test.module1
---

# module1

Test module.
"""
        )

        results = context.search_context(kb_path, "test.module1")

        assert len(results) == 1
        assert results[0]["node"] == "test.module1"
        assert results[0]["score"] == 1.0
        assert "# module1" in results[0]["content"]


def test_search_context_short_name():
    """Test short name match."""
    with TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        graph = {
            "schema_version": "v1",
            "project": "test",
            "nodes": {
                "test.storage": {
                    "type": "module",
                    "md_path": "kb/storage.md",
                    "source_path": "src/storage.py",
                    "exports": [],
                },
            },
            "edges": [],
            "stats": {},
        }
        (kb_path / "_GRAPH.json").write_text(json.dumps(graph))

        (kb_path / "storage.md").write_text(
            """---
brain_schema: "v1"
---

# storage
"""
        )

        results = context.search_context(kb_path, "storage")

        assert len(results) == 1
        assert results[0]["node"] == "test.storage"
        assert results[0]["score"] == 0.9


def test_find_matches():
    """Test match finding."""
    graph = {
        "nodes": {
            "test.module1": {
                "type": "module",
                "exports": ["func1", "func2"],
            },
            "test.module1.func1": {
                "type": "function",
                "parent": "test.module1",
                "is_private": False,
            },
            "test.module1._private": {
                "type": "function",
                "parent": "test.module1",
                "is_private": True,
            },
        }
    }

    # Exact module match (may also match symbols containing the module name)
    matches = context._find_matches(graph, "test.module1", include_private=False)
    exact_match = next((m for m in matches if m["node"] == "test.module1"), None)
    assert exact_match is not None
    assert exact_match["score"] == 1.0

    # Short name match
    matches = context._find_matches(graph, "func1", include_private=False)
    assert len(matches) >= 1
    assert any(m["node"] == "test.module1.func1" for m in matches)

    # Export match
    matches = context._find_matches(graph, "func1", include_private=False)
    module_match = next((m for m in matches if m["node"] == "test.module1"), None)
    assert module_match is not None

    # Private excluded by default
    matches = context._find_matches(graph, "_private", include_private=False)
    assert len(matches) == 0

    # Private included when requested
    matches = context._find_matches(graph, "_private", include_private=True)
    assert len(matches) == 1


def test_expand_with_dependencies():
    """Test dependency expansion."""
    graph = {
        "nodes": {
            "test.module1": {
                "type": "module",
                "exports": [],
            },
            "test.module2": {
                "type": "module",
                "exports": [],
            },
            "test.module3": {
                "type": "module",
                "exports": [],
            },
        },
        "edges": [
            {"from": "test.module1", "to": "test.module2", "type": "imports"},
            {"from": "test.module2", "to": "test.module3", "type": "imports"},
        ],
    }

    matches = [
        {
            "node": "test.module1",
            "data": graph["nodes"]["test.module1"],
            "score": 1.0,
        }
    ]

    # Depth 1: should include module2
    expanded = context._expand_with_dependencies(graph, matches, max_depth=1)
    node_names = {item["node"] for item in expanded}
    assert "test.module1" in node_names
    assert "test.module2" in node_names
    assert "test.module3" not in node_names  # Beyond depth 1

    # Depth 2: should include module3
    expanded = context._expand_with_dependencies(graph, matches, max_depth=2)
    node_names = {item["node"] for item in expanded}
    assert "test.module1" in node_names
    assert "test.module2" in node_names
    assert "test.module3" in node_names


def test_expand_with_parent():
    """Test parent expansion for symbols."""
    graph = {
        "nodes": {
            "test.module1": {
                "type": "module",
                "exports": ["func1"],
            },
            "test.module1.func1": {
                "type": "function",
                "parent": "test.module1",
                "is_private": False,
            },
        },
        "edges": [],
    }

    matches = [
        {
            "node": "test.module1.func1",
            "data": graph["nodes"]["test.module1.func1"],
            "score": 1.0,
        }
    ]

    expanded = context._expand_with_dependencies(graph, matches, max_depth=1)
    node_names = {item["node"] for item in expanded}

    # Should include parent module
    assert "test.module1" in node_names
    assert "test.module1.func1" in node_names


def test_get_module_dependencies():
    """Test transitive dependency retrieval."""
    graph = {
        "nodes": {
            "test.a": {"type": "module"},
            "test.b": {"type": "module"},
            "test.c": {"type": "module"},
        },
        "edges": [
            {"from": "test.a", "to": "test.b", "type": "imports"},
            {"from": "test.b", "to": "test.c", "type": "imports"},
        ],
    }

    # Depth 1: direct dependencies only
    deps = context._get_module_dependencies(graph, "test.a", max_depth=1)
    assert deps == {"test.b"}

    # Depth 2: transitive dependencies
    deps = context._get_module_dependencies(graph, "test.a", max_depth=2)
    assert deps == {"test.b", "test.c"}


def test_sort_by_relevance():
    """Test relevance sorting."""
    items = [
        {"node": "a", "score": 0.5},
        {"node": "b", "score": 1.0},
        {"node": "c", "score": 0.8},
    ]

    sorted_items = context._sort_by_relevance(items, "query")

    assert sorted_items[0]["node"] == "b"
    assert sorted_items[1]["node"] == "c"
    assert sorted_items[2]["node"] == "a"


def test_extract_symbol_section():
    """Test symbol section extraction."""
    content = """---
frontmatter
---

# Module

## Public API

### `func1()`

Docstring for func1.

### `func2()`

Docstring for func2.

## Classes
"""

    section = context._extract_symbol_section(content, "func1")

    assert "### `func1()`" in section
    assert "Docstring for func1" in section
    assert "func2" not in section


def test_search_context_no_graph():
    """Test behavior when graph doesn't exist."""
    with TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        results = context.search_context(kb_path, "test")

        assert results == []


def test_search_context_max_results():
    """Test max_results limit."""
    with TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # Create graph with many modules
        nodes = {
            f"test.module{i}": {
                "type": "module",
                "md_path": f"kb/module{i}.md",
                "source_path": f"src/module{i}.py",
                "exports": [],
            }
            for i in range(10)
        }
        graph = {
            "schema_version": "v1",
            "project": "test",
            "nodes": nodes,
            "edges": [],
            "stats": {},
        }
        (kb_path / "_GRAPH.json").write_text(json.dumps(graph))

        # Create markdown files
        for i in range(10):
            (kb_path / f"module{i}.md").write_text(f"# module{i}")

        results = context.search_context(kb_path, "module", max_results=3)

        assert len(results) <= 3
