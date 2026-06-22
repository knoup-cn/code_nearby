"""Context retrieval for RAG."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def search_context(
    kb_path: Path,
    query: str,
    max_results: int = 5,
    include_private: bool = False,
) -> list[dict[str, Any]]:
    """Search knowledge base for relevant context.

    Args:
        kb_path: Knowledge base root path
        query: Search query (module name, function name, or keywords)
        max_results: Maximum number of results to return
        include_private: Include private symbols in results

    Returns:
        List of context items with relevance scores
    """
    # Load graph
    graph_file = kb_path / "_GRAPH.json"
    if not graph_file.exists():
        return []

    graph = json.loads(graph_file.read_text())

    # Find matching nodes
    matches = _find_matches(graph, query, include_private)

    # Expand matches with dependencies
    expanded = _expand_with_dependencies(graph, matches, max_depth=1)

    # Sort by relevance
    sorted_results = _sort_by_relevance(expanded, query)

    # Load Markdown content
    results = []
    for item in sorted_results[:max_results]:
        content = _load_markdown_section(kb_path, item, graph)
        if content:
            results.append({
                "node": item["node"],
                "score": item["score"],
                "content": content,
            })

    return results


def _find_matches(
    graph: dict[str, Any],
    query: str,
    include_private: bool,
) -> list[dict[str, Any]]:
    """Find nodes matching the query.

    Args:
        graph: Graph dictionary
        query: Search query
        include_private: Include private symbols

    Returns:
        List of matching items with scores
    """
    query_lower = query.lower()
    matches = []

    for node_name, node_data in graph["nodes"].items():
        # Skip private symbols if not requested
        if not include_private and node_data.get("is_private", False):
            continue

        score = 0.0

        # Exact match on full name
        if node_name.lower() == query_lower:
            score = 1.0
        # Exact match on short name
        elif node_name.split(".")[-1].lower() == query_lower:
            score = 0.9
        # Partial match on full name
        elif query_lower in node_name.lower():
            score = 0.7
        # Match in exports
        elif node_data["type"] == "module":
            exports = node_data.get("exports", [])
            if any(query_lower == exp.lower() for exp in exports):
                score = 0.8
            elif any(query_lower in exp.lower() for exp in exports):
                score = 0.6

        if score > 0:
            matches.append({
                "node": node_name,
                "data": node_data,
                "score": score,
                "match_type": "direct",
            })

    return matches


def _expand_with_dependencies(
    graph: dict[str, Any],
    matches: list[dict[str, Any]],
    max_depth: int = 1,
) -> list[dict[str, Any]]:
    """Expand matches to include dependencies.

    Args:
        graph: Graph dictionary
        matches: Initial matches
        max_depth: Maximum dependency depth to traverse

    Returns:
        Expanded list with dependencies
    """
    expanded = {m["node"]: m for m in matches}

    # For each match, add its dependencies
    for match in matches:
        node_name = match["node"]

        # If it's a symbol, add its parent module
        if match["data"]["type"] in ("function", "class"):
            parent = match["data"].get("parent")
            if parent and parent not in expanded:
                expanded[parent] = {
                    "node": parent,
                    "data": graph["nodes"].get(parent, {}),
                    "score": match["score"] * 0.9,  # Higher weight for parent
                    "match_type": "parent",
                }

        # If it's a module, add its dependencies
        if match["data"]["type"] == "module":
            deps = _get_module_dependencies(graph, node_name, max_depth)
            for dep_name in deps:
                if dep_name not in expanded:
                    expanded[dep_name] = {
                        "node": dep_name,
                        "data": graph["nodes"].get(dep_name, {}),
                        "score": match["score"] * 0.7,  # Higher weight for dependencies
                        "match_type": "dependency",
                    }

    return list(expanded.values())


def _get_module_dependencies(
    graph: dict[str, Any],
    module_name: str,
    max_depth: int,
) -> set[str]:
    """Get all dependencies of a module up to max_depth.

    Args:
        graph: Graph dictionary
        module_name: Module name to get dependencies for
        max_depth: Maximum depth to traverse

    Returns:
        Set of dependency module names
    """
    if max_depth <= 0:
        return set()

    deps = set()
    for edge in graph["edges"]:
        if edge["from"] == module_name and edge["type"] == "imports":
            dep = edge["to"]
            deps.add(dep)
            # Recursively add transitive dependencies
            if max_depth > 1:
                deps.update(_get_module_dependencies(graph, dep, max_depth - 1))

    return deps


def _sort_by_relevance(
    items: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """Sort items by relevance score.

    Prioritizes modules over symbols for better RAG context.

    Args:
        items: Items to sort
        query: Original query

    Returns:
        Sorted list
    """
    def sort_key(item):
        score = item["score"]
        # Boost modules for better context (if data field exists)
        if "data" in item and item["data"].get("type") == "module":
            score += 0.1
        return (-score, item["node"])  # Negative for descending, node for stable sort

    return sorted(items, key=sort_key)


def _load_markdown_section(
    kb_path: Path,
    item: dict[str, Any],
    graph: dict[str, Any],
) -> str | None:
    """Load relevant Markdown section for an item.

    Args:
        kb_path: Knowledge base root path
        item: Item with node information
        graph: Graph dictionary

    Returns:
        Markdown content or None
    """
    node_name = item["node"]
    node_data = item["data"]

    # For modules, return the full markdown
    if node_data["type"] == "module":
        md_path = kb_path.parent / node_data.get("md_path", "")
        if md_path.exists():
            return md_path.read_text()

    # For symbols, extract the relevant section
    if node_data["type"] in ("function", "class"):
        parent = node_data.get("parent")
        if parent and parent in graph["nodes"]:
            parent_data = graph["nodes"][parent]
            md_path = kb_path.parent / parent_data.get("md_path", "")
            if md_path.exists():
                content = md_path.read_text()
                # Extract section for this symbol
                symbol_name = node_name.split(".")[-1]
                section = _extract_symbol_section(content, symbol_name)
                # If no section found, return full module content
                return section if section else content

    return None


def _extract_symbol_section(content: str, symbol_name: str) -> str:
    """Extract section for a specific symbol from markdown.

    Args:
        content: Full markdown content
        symbol_name: Symbol name to extract

    Returns:
        Extracted section
    """
    lines = content.split("\n")
    section_lines = []
    in_section = False
    current_level = 0

    for line in lines:
        # Check if this is a heading
        if line.startswith("#"):
            heading_parts = line.split()
            if not heading_parts:
                continue

            level = len(heading_parts[0])
            heading_text = line.lstrip("#").strip()

            # Match symbol name in heading (e.g., "### `func_name()`")
            if f"`{symbol_name}" in heading_text:
                in_section = True
                current_level = level
                section_lines.append(line)
            elif in_section and level <= current_level:
                # End of our section (another heading at same or higher level)
                break
            elif in_section:
                section_lines.append(line)
        elif in_section:
            section_lines.append(line)

    return "\n".join(section_lines) if section_lines else ""
