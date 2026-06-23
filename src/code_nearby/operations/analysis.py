"""代码分析入口——产出 RAG 索引 + 依赖图。"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from code_nearby import config, fs_utils, graph, storage
from code_nearby.rag import chunker
from code_nearby.rag.index import OldSchemaError, RagIndex
from code_nearby.tree_sitter_utils import relative_path


def run_full_analysis(project_path: Path, full_rebuild: bool = False) -> dict:
    """分析源码目录，产出 RAG 索引 + 依赖图。

    一次文件变更检测 + 共享 CST 遍历，写入 SQLite FTS5 检索索引，
    并生成 ``_GRAPH.json`` 依赖图供检索时做结构加分。

    Args:
        project_path: 源码目录路径
        full_rebuild: 是否从头重建

    Returns:
        {
            "success": bool,
            "files_analyzed": int,
            "added": int, "modified": int, "deleted": int,
            "chunks_added": int, "chunks_updated": int, "chunks_deleted": int,
            "chunks_total": int,
            "kb_path": str | None,
            "error": str | None,
        }
    """
    kb_path = config.get_kb_path()

    try:
        project_kb_path = storage.ensure_project_kb_path(kb_path, project_path)
    except RuntimeError as e:
        return {"success": False, "error": str(e)}

    metadata = storage.load_project_metadata(kb_path, project_path)

    # 时间锚点（替代 commit hash）
    index_start_time = time.time()

    # --- 准备 RAG 目录 ---
    rag_dir = project_kb_path / ".rag"

    # --- 文件发现 ---
    all_files = fs_utils.discover_files(project_path)

    # --- 全量重建清理（必须在打开索引前） ---
    if full_rebuild:
        shutil.rmtree(rag_dir, ignore_errors=True)

    # --- 打开索引（仅一次，损坏防御 + 旧 schema 迁移） ---
    try:
        index = RagIndex.open(rag_dir / "index.sqlite3")
    except OldSchemaError:
        shutil.rmtree(rag_dir, ignore_errors=True)
        index = RagIndex.open(rag_dir / "index.sqlite3")
        # 旧 schema 自动迁移：清空后全量重建
        changes = {"added": all_files, "modified": [], "deleted": []}
    except sqlite3.DatabaseError:
        if not full_rebuild:
            shutil.rmtree(rag_dir, ignore_errors=True)
            index = RagIndex.open(rag_dir / "index.sqlite3")
            # 损坏恢复：索引已重建为空库，changes 必须重置为全量模式，
            # 否则增量 diff 中未变更的文件会永久丢失
            changes = {"added": all_files, "modified": [], "deleted": []}
        else:
            raise

    chunks_added = chunks_updated = chunks_deleted = 0
    try:
        with index:
            # --- 变更检测 ---
            if full_rebuild or not metadata:
                changes = {
                    "added": all_files,
                    "modified": [],
                    "deleted": [],
                }
            elif "changes" not in locals():
                # 非损坏恢复的正常增量路径
                last_index_time = metadata.get("last_indexed_at", 0)
                changed = fs_utils.detect_changed_files(project_path, last_index_time, all_files)

                indexed_paths = set(index.list_files())
                current_paths = {relative_path(f, project_path) for f in all_files}

                # 缓存 relative_path 避免同一文件重复计算
                changed_rel = {f: relative_path(f, project_path) for f in changed}
                added = [f for f, rp in changed_rel.items() if rp not in indexed_paths]
                modified = [f for f, rp in changed_rel.items() if rp in indexed_paths]
                deleted = [project_path / p for p in indexed_paths if p not in current_paths]
                changes = {
                    "added": added,
                    "modified": modified,
                    "deleted": deleted,
                }

            # --- 事务边界：整批文件原子写入 ---
            for file_path in changes["added"] + changes["modified"]:
                if not file_path.exists():
                    continue

                rel = relative_path(file_path, project_path)
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
                rel = relative_path(file_path, project_path)
                chunks_deleted += index.delete_file(rel)

            total_chunks = index.count()

        # --- 依赖图 ---
        project_name = project_path.resolve().name
        try:
            g = graph.generate_graph(index, project_name)
            graph.save_graph(g, project_kb_path)
        except Exception as e:
            logging.warning(f"Failed to generate graph: {e}")
    finally:
        index.close()

    # --- 保存元数据 ---
    storage.save_project_metadata(
        kb_path,
        project_path,
        {
            "last_analyzed": datetime.now(UTC).isoformat(),
            "last_indexed_at": index_start_time,
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
