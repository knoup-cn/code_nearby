"""源码分析和索引构建。"""
from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from brain import analyzer, config, git_utils, storage
from brain.rag import chunker
from brain.rag.index import RagIndex


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
    from brain.operations.indexing import _generate_project_graph, _generate_project_index
    from brain.operations.sync import sync_knowledge_base

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
        # Full analysis: all tracked files plus untracked, non-ignored files
        # (parity with the incremental path, which also picks up untracked).
        try:
            tracked_files = git_utils.get_tracked_files(project_path)
            untracked_files = git_utils.get_untracked_files(project_path)
        except git_utils.GitCommandError as e:
            return {"success": False, "error": str(e)}

        changes = {"modified": [], "added": tracked_files + untracked_files, "deleted": []}
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
            untracked = git_utils.get_untracked_files(project_path)
        except git_utils.GitCommandError as e:
            return {"success": False, "error": str(e)}
        changes = {"added": tracked + untracked, "modified": [], "deleted": []}
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
