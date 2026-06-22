"""代码分析入口——产出 RAG 索引 + 依赖图。"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from brain import config, git_utils, graph, storage
from brain.rag import chunker
from brain.rag.index import RagIndex


def run_full_analysis(project_path: Path, full_rebuild: bool = False) -> dict:
    """分析源码仓库，产出 RAG 索引 + 依赖图。

    一次文件变更检测 + 共享 CST 遍历，写入 SQLite FTS5 检索索引，
    并生成 ``_GRAPH.json`` 依赖图供检索时做结构加分。

    Args:
        project_path: 源仓库路径
        full_rebuild: 是否从头重建

    Returns:
        {
            "success": bool,
            "files_analyzed": int,
            "added": int, "modified": int, "deleted": int,
            "chunks_total": int,
            "kb_path": str | None,
            "error": str | None,
        }
    """
    # 加载配置
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

    # --- 检测变更 ---
    if full_rebuild or not metadata:
        try:
            tracked = git_utils.get_tracked_files(project_path)
            untracked = git_utils.get_untracked_files(project_path)
        except git_utils.GitCommandError as e:
            return {"success": False, "error": str(e)}
        changes = {"modified": [], "added": tracked + untracked, "deleted": []}
    else:
        try:
            last_commit = metadata.get("last_commit")
            changes = git_utils.get_changed_files(project_path, last_commit)
        except git_utils.GitCommandError as e:
            return {"success": False, "error": str(e)}

    # --- 准备 RAG 索引 ---
    rag_dir = project_kb_path / ".rag"
    _ensure_rag_gitignore(kb_path)
    if full_rebuild:
        shutil.rmtree(rag_dir, ignore_errors=True)
    index = RagIndex.open(rag_dir / "index.sqlite3")

    chunks_added = chunks_updated = chunks_deleted = 0
    try:
        # --- 对每个变更文件产出 RAG chunk ---
        for file_path in changes["added"] + changes["modified"]:
            if not file_path.exists():
                continue

            rel = chunker.relative_path(file_path, project_path)
            new_chunks = chunker.chunk_file(file_path, project_path)
            existing = index.file_manifest(rel)
            new_by_id = {c.chunk_id: c for c in new_chunks}

            vanished = [cid for cid in existing if cid not in new_by_id]
            to_upsert = [c for c in new_chunks if existing.get(c.chunk_id) != c.content_hash]
            chunks_deleted += index.delete_chunks(vanished)
            for chunk in to_upsert:
                if chunk.chunk_id in existing:
                    chunks_updated += 1
                else:
                    chunks_added += 1
            index.upsert(to_upsert)

        # 清理已删除文件
        for file_path in changes["deleted"]:
            rel = chunker.relative_path(file_path, project_path)
            chunks_deleted += index.delete_file(rel)

        total_chunks = index.count()

        # --- 依赖图 ---
        project_name = project_path.resolve().name
        try:
            g = graph.generate_graph(index, project_name)
            graph.save_graph(g, project_kb_path)
        except Exception as e:
            import sys

            print(f"Warning: Failed to generate graph: {e}", file=sys.stderr)
    finally:
        index.close()

    # --- 保存元数据 ---
    storage.save_project_metadata(
        kb_path,
        project_path,
        {
            "last_analyzed": datetime.now(UTC).isoformat(),
            "last_indexed": datetime.now(UTC).isoformat(),
            "last_commit": current_commit,
            "last_indexed_commit": current_commit,
            "kb_location": str(project_kb_path.relative_to(kb_path)),
            "rag_location": str(rag_dir.relative_to(kb_path)),
        },
    )

    total = len(changes["added"]) + len(changes["modified"])
    return {
        "success": True,
        "files_analyzed": total,
        "added": len(changes["added"]),
        "modified": len(changes["modified"]),
        "deleted": len(changes["deleted"]),
        "chunks_added": chunks_added,
        "chunks_updated": chunks_updated,
        "chunks_deleted": chunks_deleted,
        "chunks_total": total_chunks,
        "kb_path": str(project_kb_path.relative_to(kb_path)),
        "error": None,
    }


def _ensure_rag_gitignore(kb_path: Path) -> None:
    """将派生的、二进制的 ``.rag/`` 索引排除在知识库仓库之外。"""
    gitignore = kb_path / ".gitignore"
    rule = "**/.rag/"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if rule in existing.split():
        return
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    gitignore.write_text(f"{existing}{prefix}{rule}\n", encoding="utf-8")
