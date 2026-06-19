"""Core operations (business logic)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain import analyzer, config, git_utils, storage


def needs_overwrite(path: Path) -> bool:
    """Return whether initialization would replace an existing directory."""
    return path.exists() and any(path.iterdir())


def init_config(
    git_repo: str | None, kb_path: Path, overwrite: bool = False
) -> tuple[bool, str]:
    """Initialize knowledge base configuration.

    Args:
        git_repo: Git repository URL for the knowledge base (read-write)
        kb_path: Resolved local path for the knowledge base repository
        overwrite: Whether to overwrite existing non-empty directory

    Returns:
        (success, message)
    """
    if not git_repo:
        return False, "Git repository is required (knowledge base is stored in git)"

    git_repo = git_repo.strip()
    resolved_path = str(kb_path)

    # Knowledge base repository: test connection and clone
    success, message = git_utils.test_git_connection(git_repo)
    if not success:
        return False, f"Git connection failed: {message}"

    success, message = git_utils.clone_repo(git_repo, kb_path, overwrite=overwrite)
    if not success:
        return False, f"Clone failed: {message}"

    # Save configuration (both fields required)
    cfg = {
        "git_repo": git_repo,
        "local_path": resolved_path,
    }
    config.save_config(cfg)
    return True, f"Knowledge base initialized at {resolved_path}"


def get_status() -> dict | None:
    """Get current configuration."""
    return config.load_config() if config.is_initialized() else None


def clear_config() -> bool:
    """Clear configuration."""
    if not config.is_initialized():
        return False
    config.get_config_path().unlink()
    return True


def is_git_repo(path: Path) -> bool:
    """Check if path is a Git repository."""
    return git_utils.is_git_repo(path)


def analyze_project(
    project_path: Path, full_rebuild: bool = False, auto_sync: bool = False
) -> dict:
    """Analyze source Git repository incrementally.

    Args:
        project_path: Path to the source repository (read-only)
        full_rebuild: Whether to rebuild knowledge base from scratch
        auto_sync: Whether to automatically commit and push changes to the knowledge base

    Returns:
        {
            "success": bool,
            "files_analyzed": int,
            "added": int,
            "modified": int,
            "deleted": int,
            "kb_path": str | None,  # Project's knowledge base path (org/project)
            "synced": bool | None,  # Whether changes were committed/pushed (if auto_sync=True)
            "sync_commit": str | None,  # Commit hash if synced
            "error": str | None
        }
    """
    # Load knowledge base configuration
    cfg = config.load_config()
    kb_root = cfg.get("local_path")
    if not kb_root:
        return {"success": False, "error": "Knowledge base not initialized"}

    kb_path = Path(kb_root)

    # Ensure project has org/project structure in the knowledge base
    try:
        project_kb_path = storage.ensure_project_kb_path(kb_path, project_path)
    except RuntimeError as e:
        return {"success": False, "error": str(e)}

    # Load project metadata
    metadata = storage.load_project_metadata(kb_path, project_path)

    # Detect changes in the source repository
    try:
        current_commit = git_utils.require_current_commit(project_path)
    except git_utils.GitCommandError as e:
        return {"success": False, "error": str(e)}

    if full_rebuild or not metadata:
        # Full analysis: all tracked files
        try:
            tracked_files = git_utils.get_tracked_files(project_path)
        except git_utils.GitCommandError as e:
            return {"success": False, "error": str(e)}

        changes = {"modified": [], "added": tracked_files, "deleted": []}
    else:
        # Incremental analysis
        try:
            last_commit = metadata.get("last_commit")
            changes = git_utils.get_changed_files(project_path, last_commit)
        except git_utils.GitCommandError as e:
            return {"success": False, "error": str(e)}

    # Execute analysis and update the knowledge base
    for file_path in changes["added"] + changes["modified"]:
        if file_path.exists():
            analyzer.analyze_file(file_path, project_kb_path, project_path)

    # Clean up deleted files from the knowledge base
    for file_path in changes["deleted"]:
        storage.remove_file_from_kb(project_kb_path, project_path, file_path)

    # Update metadata in the knowledge base
    storage.save_project_metadata(
        kb_path,
        project_path,
        {
            "last_analyzed": datetime.now(UTC).isoformat(),
            "last_commit": current_commit,
            "kb_location": str(project_kb_path.relative_to(kb_path)),
        },
    )

    # Generate Obsidian index files
    _generate_project_index(project_kb_path, project_path)

    # Generate dependency graph
    _generate_project_graph(project_kb_path, project_path)

    total = len(changes["added"]) + len(changes["modified"])
    result = {
        "success": True,
        "files_analyzed": total,
        "added": len(changes["added"]),
        "modified": len(changes["modified"]),
        "deleted": len(changes["deleted"]),
        "kb_path": str(project_kb_path.relative_to(kb_path)),
        "synced": None,
        "sync_commit": None,
        "error": None,
    }

    # Auto-sync to the knowledge base repository if requested
    if auto_sync and total > 0:
        changes_summary = (
            f"{result['added']} added, "
            f"{result['modified']} modified, "
            f"{result['deleted']} deleted"
        )
        sync_result = sync_knowledge_base(
            kb_path,
            project_path,
            changes_summary=changes_summary,
        )
        result["synced"] = sync_result["success"]
        result["sync_commit"] = sync_result.get("commit")
        if not sync_result["success"]:
            result["error"] = sync_result.get("error")

    return result


def index_project(project_path: Path, full_rebuild: bool = False) -> dict:
    """Build/update the Goal-2 lexical+structural RAG index for a project.

    Mirrors :func:`analyze_project` but writes a per-project SQLite FTS5 index
    under ``{kb}/{org}/{project}/.rag/`` instead of Markdown. Incremental at the
    chunk level (G4): only chunks whose content hash changed are re-indexed.

    Returns:
        {
            "success": bool,
            "files_indexed": int,
            "chunks_added": int,
            "chunks_updated": int,
            "chunks_deleted": int,
            "chunks_total": int,
            "kb_path": str | None,
            "error": str | None,
        }
    """
    import shutil

    from brain.rag import chunker
    from brain.rag.index import RagIndex

    cfg = config.load_config()
    kb_root = cfg.get("local_path")
    if not kb_root:
        return {"success": False, "error": "Knowledge base not initialized"}

    kb_path = Path(kb_root)
    try:
        project_kb_path = storage.ensure_project_kb_path(kb_path, project_path)
    except RuntimeError as e:
        return {"success": False, "error": str(e)}

    metadata = storage.load_project_metadata(kb_path, project_path)
    try:
        current_commit = git_utils.require_current_commit(project_path)
    except git_utils.GitCommandError as e:
        return {"success": False, "error": str(e)}

    last_indexed = None if full_rebuild else (metadata or {}).get("last_indexed_commit")

    rag_dir = project_kb_path / ".rag"
    _ensure_rag_gitignore(kb_path)

    if full_rebuild or not last_indexed:
        try:
            tracked = git_utils.get_tracked_files(project_path)
        except git_utils.GitCommandError as e:
            return {"success": False, "error": str(e)}
        changes = {"added": tracked, "modified": [], "deleted": []}
        if full_rebuild:
            shutil.rmtree(rag_dir, ignore_errors=True)
    else:
        try:
            changes = git_utils.get_changed_files(project_path, last_indexed)
        except git_utils.GitCommandError as e:
            return {"success": False, "error": str(e)}

    added = updated = deleted = 0
    files_indexed = 0
    index = RagIndex.open(rag_dir / "index.sqlite3")
    try:
        for file_path in changes["added"] + changes["modified"]:
            if not file_path.exists():
                continue
            rel = chunker.relative_path(file_path, project_path)
            new_chunks = chunker.chunk_file(file_path, project_path)
            existing = index.file_manifest(rel)
            new_by_id = {c.chunk_id: c for c in new_chunks}

            vanished = [cid for cid in existing if cid not in new_by_id]
            to_upsert = [
                c for c in new_chunks if existing.get(c.chunk_id) != c.content_hash
            ]
            deleted += index.delete_chunks(vanished)
            for chunk in to_upsert:
                if chunk.chunk_id in existing:
                    updated += 1
                else:
                    added += 1
            index.upsert(to_upsert)
            if new_chunks:
                files_indexed += 1

        for file_path in changes["deleted"]:
            rel = chunker.relative_path(file_path, project_path)
            deleted += index.delete_file(rel)

        chunks_total = index.count()
    finally:
        index.close()

    storage.save_project_metadata(
        kb_path,
        project_path,
        {
            "last_indexed": datetime.now(UTC).isoformat(),
            "last_indexed_commit": current_commit,
            "rag_location": str(rag_dir.relative_to(kb_path)),
        },
    )

    return {
        "success": True,
        "files_indexed": files_indexed,
        "chunks_added": added,
        "chunks_updated": updated,
        "chunks_deleted": deleted,
        "chunks_total": chunks_total,
        "kb_path": str(project_kb_path.relative_to(kb_path)),
        "error": None,
    }


def _ensure_rag_gitignore(kb_path: Path) -> None:
    """Keep the derived, binary ``.rag/`` index out of the knowledge-base repo."""
    gitignore = kb_path / ".gitignore"
    rule = "**/.rag/"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if rule in existing.split():
        return
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    gitignore.write_text(f"{existing}{prefix}{rule}\n", encoding="utf-8")


def sync_knowledge_base(
    kb_path: Path, project_path: Path, changes_summary: str
) -> dict:
    """Commit and push knowledge base changes.

    Args:
        kb_path: Knowledge base root path
        project_path: Source project path (for commit message)
        changes_summary: Summary of changes (e.g., "3 added, 2 modified, 1 deleted")

    Returns:
        {
            "success": bool,
            "commit": str | None,  # Commit hash if successful
            "pushed": bool,  # Whether push succeeded
            "error": str | None
        }
    """
    # Check if KB is a git repository
    if not git_utils.is_git_repo(kb_path):
        return {
            "success": False,
            "commit": None,
            "pushed": False,
            "error": "Knowledge base is not a git repository",
        }

    # Check if there are changes
    if not git_utils.has_changes(kb_path):
        return {
            "success": True,
            "commit": None,
            "pushed": False,
            "error": None,
        }

    try:
        # Get project identity for commit message
        remote_url = git_utils.get_remote_url(project_path)
        if remote_url:
            identity = git_utils.parse_repo_identity(remote_url)
            project_name = f"{identity[0]}/{identity[1]}" if identity else project_path.name
        else:
            project_name = project_path.name

        # Stage all changes
        git_utils.git_add(kb_path)

        # Create commit
        commit_message = f"Update {project_name}: {changes_summary}"
        commit_hash = git_utils.git_commit(kb_path, commit_message)

        # Push to remote
        pushed = False
        push_error = None
        try:
            git_utils.git_push(kb_path)
            pushed = True
        except git_utils.GitCommandError as e:
            push_error = str(e)

        return {
            "success": True,
            "commit": commit_hash,
            "pushed": pushed,
            "error": push_error,
        }

    except git_utils.GitCommandError as e:
        return {
            "success": False,
            "commit": None,
            "pushed": False,
            "error": str(e),
        }


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
