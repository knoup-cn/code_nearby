"""Obsidian 索引文件生成。"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain import git_utils


def _generate_project_index(kb_path: Path, project_path: Path) -> None:
    """Generate Obsidian index files (_PROJECT.md and _MODULES.md).

    Args:
        kb_path: Project's knowledge base path (org/project/)
        project_path: Source project path
    """
    project_name = project_path.name

    # Get org/project from git remote
    remote_url = git_utils.get_remote_url(project_path)
    if remote_url:
        identity = git_utils.parse_repo_identity(remote_url)
        org_name = identity[0] if identity else "unknown"
    else:
        org_name = "unknown"

    # Collect all analyzed modules
    modules: list[dict[str, str | int]] = []
    for md_file in kb_path.rglob("*.md"):
        if md_file.name.startswith("_"):
            continue

        # Parse frontmatter to extract metadata
        content = md_file.read_text(encoding="utf-8")
        if content.startswith("---"):
            yaml_end = content.find("---", 3)
            if yaml_end != -1:
                frontmatter_text = content[3:yaml_end].strip()
                metadata = _parse_simple_yaml(frontmatter_text)

                relative = md_file.relative_to(kb_path).with_suffix("")
                modules.append(
                    {
                        "name": md_file.stem,
                        "path": str(relative),
                        "type": metadata.get("type", "unknown"),
                        "exports_count": len(metadata.get("exports", [])),
                        "lines_of_code": metadata.get("lines_of_code", 0),
                    }
                )

    # Generate _PROJECT.md
    project_lines = [
        "---",
        "type: project-index",
        f"project: {project_name}",
        f"organization: {org_name}",
        "tags: [index, project, moc]",
        "---",
        "",
        f"# {project_name}",
        "",
        f"Knowledge base for `{org_name}/{project_name}`.",
        "",
        "## Quick Links",
        "",
        "- [[_MODULES]] - Module index",
        "",
        "## Statistics",
        "",
        f"- **Total modules**: {len(modules)}",
        f"- **Total exports**: {sum(m['exports_count'] for m in modules)}",
        f"- **Lines of code**: {sum(m['lines_of_code'] for m in modules)}",
        "",
        "## Recent Analysis",
        "",
        f"Last updated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## All Modules",
        "",
    ]

    for mod in sorted(modules, key=lambda m: m["path"]):
        exports_str = f" — {mod['exports_count']} exports" if mod["exports_count"] > 0 else ""
        project_lines.append(f"- [[{mod['path']}]]{exports_str}")

    project_lines.extend(
        [
            "",
            "---",
            "",
            "## Dataview Queries",
            "",
            "### By Lines of Code",
            "",
            "```dataview",
            "TABLE type, lines_of_code, length(exports) AS \"Exports\"",
            "FROM #python",
            "SORT lines_of_code DESC",
            "```",
            "",
            "### Core Modules",
            "",
            "```dataview",
            "LIST",
            "FROM #core",
            "SORT file.name",
            "```",
        ]
    )

    (kb_path / "_PROJECT.md").write_text("\n".join(project_lines), encoding="utf-8")

    # Generate _MODULES.md (categorized view)
    modules_lines = [
        "---",
        "type: module-index",
        f"project: {project_name}",
        "tags: [index, modules]",
        "---",
        "",
        f"# {project_name} Modules",
        "",
        "Categorized view of all modules in the knowledge base.",
        "",
        "## By Type",
        "",
    ]

    # Group by type
    by_type: dict[str, list[dict[str, str | int]]] = {}
    for mod in modules:
        mod_type = str(mod["type"])
        if mod_type not in by_type:
            by_type[mod_type] = []
        by_type[mod_type].append(mod)

    for mod_type in sorted(by_type.keys()):
        modules_lines.append(f"### {mod_type}")
        modules_lines.append("")
        for mod in sorted(by_type[mod_type], key=lambda m: m["name"]):
            modules_lines.append(f"- [[{mod['path']}]]")
        modules_lines.append("")

    modules_lines.extend(
        [
            "---",
            "",
            "**Back to**: [[_PROJECT]]",
        ]
    )

    (kb_path / "_MODULES.md").write_text("\n".join(modules_lines), encoding="utf-8")


def _generate_project_graph(kb_path: Path, project_path: Path) -> None:
    """Generate dependency graph (_GRAPH.json).

    Args:
        kb_path: Project's knowledge base path (org/project/)
        project_path: Source project path
    """
    from brain import graph

    project_name = project_path.resolve().name

    try:
        # Generate graph
        g = graph.generate_graph(kb_path, project_name)
        # Save to _GRAPH.json
        graph.save_graph(g, kb_path)
    except Exception as e:
        # Don't fail the entire analyze operation if graph generation fails
        import sys
        print(f"Warning: Failed to generate graph: {e}", file=sys.stderr)


def _parse_simple_yaml(yaml_text: str) -> dict[str, Any]:
    """Parse simple YAML frontmatter (no external dependencies).

    Args:
        yaml_text: YAML text without --- markers

    Returns:
        Parsed dictionary
    """
    result: dict[str, Any] = {}
    current_key = None
    current_list: list[str] = []

    for line in yaml_text.split("\n"):
        line = line.rstrip()
        if not line:
            continue

        # List item
        if line.startswith("  - "):
            item = line[4:].strip().strip('"')
            current_list.append(item)
        # Key-value pair
        elif ":" in line and not line.startswith(" "):
            if current_key and current_list:
                result[current_key] = current_list
                current_list = []

            key, _, value = line.partition(":")
            current_key = key.strip()
            value = value.strip().strip('"')

            if value:
                # Try to convert to int
                try:
                    result[current_key] = int(value)
                except ValueError:
                    result[current_key] = value
            else:
                # Next lines might be a list
                pass

    # Flush last list
    if current_key and current_list:
        result[current_key] = current_list

    return result
