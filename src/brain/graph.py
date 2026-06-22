"""Graph generation for knowledge base."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def generate_graph(kb_path: Path, project_name: str) -> dict[str, Any]:
    """Generate dependency graph from all Markdown files.

    Args:
        kb_path: Knowledge base root path
        project_name: Project name (e.g., "brain")

    Returns:
        Graph dictionary with nodes and edges
    """
    graph: dict[str, Any] = {
        "schema_version": "v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "project": project_name,
        "nodes": {},
        "edges": [],
    }

    # Scan all Markdown files
    md_files = list(kb_path.glob("**/*.md"))
    md_files = [f for f in md_files if not f.name.startswith("_")]

    # First pass: add all nodes
    for md_file in md_files:
        _add_nodes(md_file, kb_path, graph)

    # Second pass: add edges (now all nodes exist)
    for md_file in md_files:
        _add_edges(md_file, graph)

    # Add statistics
    graph["stats"] = {
        "total_modules": sum(1 for n in graph["nodes"].values() if n["type"] == "module"),
        "total_symbols": sum(
            1 for n in graph["nodes"].values() if n["type"] in ("function", "class")
        ),
        "total_edges": len(graph["edges"]),
    }

    return graph


def _add_nodes(md_file: Path, kb_path: Path, graph: dict[str, Any]) -> None:
    """Add nodes from a single Markdown file.

    Args:
        md_file: Path to Markdown file
        kb_path: Knowledge base root path
        graph: Graph dictionary to update
    """
    content = md_file.read_text()

    # Parse frontmatter
    frontmatter = _parse_frontmatter(content)
    if not frontmatter or frontmatter.get("brain_schema") != "v1":
        return

    module_name = frontmatter.get("module")
    if not module_name:
        return

    # Add module node
    graph["nodes"][module_name] = {
        "type": "module",
        "md_path": str(md_file.relative_to(kb_path.parent)),
        "source_path": frontmatter.get("source_path", ""),
        "exports": frontmatter.get("exports", []),
        "lines_of_code": frontmatter.get("lines_of_code", 0),
    }

    # Add symbol nodes
    for symbol in frontmatter.get("symbols", []):
        symbol_full_name = f"{module_name}.{symbol['name']}"
        graph["nodes"][symbol_full_name] = {
            "type": symbol["type"],
            "parent": module_name,
            "signature": symbol.get("signature", ""),
            "location_hint": symbol.get("location_hint", 0),
            "is_private": symbol.get("is_private", False),
        }

        # Add is_async for functions
        if symbol["type"] == "function":
            graph["nodes"][symbol_full_name]["is_async"] = symbol.get("is_async", False)


def _add_edges(md_file: Path, graph: dict[str, Any]) -> None:
    """Add edges from a single Markdown file.

    Args:
        md_file: Path to Markdown file
        graph: Graph dictionary to update
    """
    content = md_file.read_text()

    # Parse frontmatter
    frontmatter = _parse_frontmatter(content)
    if not frontmatter or frontmatter.get("brain_schema") != "v1":
        return

    module_name = frontmatter.get("module")
    if not module_name:
        return

    # Add import edges
    dependencies = frontmatter.get("dependencies", [])
    for dep in dependencies:
        # Extract module name from wikilink [[module]]
        dep_clean = dep.strip('[]"')
        # Try to find full module name
        dep_module = _resolve_dependency(dep_clean, graph["nodes"])
        if dep_module:
            edge = {
                "from": module_name,
                "to": dep_module,
                "type": "imports",
                "metadata": {},
            }
            # Avoid duplicates
            if edge not in graph["edges"]:
                graph["edges"].append(edge)


def _process_markdown(md_file: Path, kb_path: Path, graph: dict[str, Any]) -> None:
    """Process a single Markdown file and add to graph (deprecated).

    This function is deprecated. Use _add_nodes() and _add_edges() instead.

    Args:
        md_file: Path to Markdown file
        kb_path: Knowledge base root path
        graph: Graph dictionary to update
    """
    _add_nodes(md_file, kb_path, graph)
    _add_edges(md_file, graph)


def _parse_frontmatter(content: str) -> dict[str, Any] | None:
    """Parse YAML frontmatter from Markdown.

    Args:
        content: Markdown content

    Returns:
        Parsed frontmatter or None if not found
    """
    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        return yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None


def _resolve_dependency(dep_name: str, nodes: dict[str, Any]) -> str | None:
    """Resolve a dependency name to a full module name.

    Import dependencies always point at modules, so resolution is restricted to
    module nodes. This prevents colliding with a symbol that happens to share the
    dependency's leaf name (e.g. a CLI command ``context`` vs. the ``brain.context``
    module). Suffix matches are sorted so the result is deterministic regardless of
    node insertion order.

    Args:
        dep_name: Dependency name from a wikilink (e.g., "storage" or "brain.storage")
        nodes: All graph nodes

    Returns:
        Full module name (e.g., "brain.storage") or None
    """
    module_names = [name for name, node in nodes.items() if node.get("type") == "module"]

    # Try exact match first
    if dep_name in module_names:
        return dep_name

    # Fall back to a suffix match against module nodes only (deterministic)
    candidates = sorted(name for name in module_names if name.endswith(f".{dep_name}"))
    return candidates[0] if candidates else None


def save_graph(graph: dict[str, Any], kb_path: Path) -> Path:
    """Save graph to _GRAPH.json.

    Args:
        graph: Graph dictionary
        kb_path: Knowledge base root path

    Returns:
        Path to saved graph file
    """
    graph_file = kb_path / "_GRAPH.json"
    graph_file.write_text(json.dumps(graph, indent=2))
    return graph_file
