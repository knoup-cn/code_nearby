"""实时增量索引——基于 watchdog 的文件监听与自动重建。

监听项目目录的文件变更（创建/修改/删除），自动触发受影响文件
的 chunk 重建与索引更新，保持索引与磁盘实时同步。

可作为独立 daemon（``nearby watch``）或嵌入 MCP server。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from code_nearby import fs_utils, graph, storage
from code_nearby.lang_config import LANGUAGES_BY_SUFFIX
from code_nearby.rag import chunker
from code_nearby.rag.index import RagIndex
from code_nearby.tree_sitter_utils import relative_path

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# 文件保存后等待 debounce 秒再处理（避免读到未写完的文件）
DEBOUNCE_SECONDS = 0.5
# 图重生成的变更最小间隔（秒）
GRAPH_COOLDOWN = 5.0
# 启动时是否立即全量索引（如果没有索引的话）
AUTO_INITIAL_INDEX = True


class IndexEventHandler(FileSystemEventHandler):
    """watchdog 事件 → 增量索引更新。

    仅处理后缀在 ``LANGUAGES_BY_SUFFIX`` 中的源文件，
    自动遵循 .gitignore 与内置忽略目录。
    """

    def __init__(
        self,
        project_path: Path,
        index: RagIndex,
        rag_dir: Path,
        *,
        on_indexed: Callable[[str, int], None] | None = None,
    ) -> None:
        super().__init__()
        self._project_path = project_path
        self._index = index
        self._rag_dir = rag_dir
        self._on_indexed = on_indexed
        self._pending: dict[str, float] = {}  # rel_path → 最后事件时间
        self._last_graph_regen = 0.0
        # 加载 ignore spec 用于增量过滤
        self._ignore_spec = fs_utils._load_gitignore_spec(project_path)

    # --- watchdog callbacks -------------------------------------------------

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule(event.src_path)  # type: ignore[arg-type]

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule(event.src_path)  # type: ignore[arg-type]

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle_delete(event.src_path)  # type: ignore[arg-type]

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            # 旧路径：删除；新路径：重建
            self._handle_delete(event.src_path)  # type: ignore[arg-type]
            # dest_path 在 FileSystemMovedEvent 中
            dest = getattr(event, "dest_path", "")
            if dest:
                self._schedule(dest)

    # --- internal -----------------------------------------------------------

    def _should_ignore(self, abs_path: str) -> bool:
        """检查是否应忽略此文件。"""
        file_path = Path(abs_path)
        # 后缀过滤：只处理已知语言
        if file_path.suffix not in LANGUAGES_BY_SUFFIX:
            return True
        # 目录过滤
        for part in file_path.parts:
            if part in fs_utils.DEFAULT_IGNORE_DIRS:
                return True
        # .gitignore 过滤
        if self._ignore_spec is not None:
            try:
                rel = str(file_path.relative_to(self._project_path))
            except ValueError:
                return True
            if self._ignore_spec.match_file(rel):
                return True
        # basename 过滤
        import fnmatch

        for pattern in fs_utils.DEFAULT_IGNORE_PATTERNS:
            if fnmatch.fnmatch(file_path.name, pattern):
                return True
        return False

    def _schedule(self, abs_path: str) -> None:
        """将文件加入待处理队列（debounce）。"""
        if self._should_ignore(abs_path):
            return
        try:
            rel = relative_path(Path(abs_path), self._project_path)
        except ValueError:
            return
        self._pending[rel] = time.monotonic()

    def _handle_delete(self, abs_path: str) -> None:
        """直接处理删除事件（无需 debounce）。"""
        if self._should_ignore(abs_path):
            return
        try:
            rel = relative_path(Path(abs_path), self._project_path)
        except ValueError:
            return
        try:
            count = self._index.delete_file(rel)
            if count > 0:
                logger.info("watch: deleted %d chunks for %s", count, rel)
                if self._on_indexed:
                    self._on_indexed(rel, -count)
        except Exception:
            logger.exception("watch: failed to delete chunks for %s", rel)

    # --- 主循环 -------------------------------------------------------------

    def process_pending(self) -> None:
        """处理所有过 debounce 期的待处理文件（由外部循环调用）。

        此方法应定期调用（例如每秒一次）。对每个已就绪的文件：
        删除旧 chunk → 重新分块 → upsert。
        """
        if not self._pending:
            return

        now = time.monotonic()
        ready = {rel for rel, ts in self._pending.items() if now - ts >= DEBOUNCE_SECONDS}
        if not ready:
            return

        # 按批处理，避免重复重建同一个文件
        for rel in sorted(ready):
            del self._pending[rel]
            file_path = self._project_path / rel
            if not file_path.exists():
                # 文件在 debounce 期间被删除了
                count = self._index.delete_file(rel)
                if count > 0 and self._on_indexed:
                    self._on_indexed(rel, -count)
                continue

            try:
                # 删除旧 chunk
                self._index.delete_file(rel)
                # 重新分块
                new_chunks = chunker.chunk_file(file_path, self._project_path)
                if new_chunks:
                    self._index.upsert(new_chunks)
                count = len(new_chunks)
                logger.info("watch: re-indexed %s (%d chunks)", rel, count)
                if self._on_indexed:
                    self._on_indexed(rel, count)
            except Exception:
                logger.exception("watch: failed to re-index %s", rel)

    def maybe_regen_graph(self, project_name: str, kb_path: Path) -> bool:
        """如果自上次图生成以来已有足够时间，重新生成依赖图。

        Returns:
            True 如果图已更新
        """
        now = time.monotonic()
        if now - self._last_graph_regen < GRAPH_COOLDOWN:
            return False
        try:
            g = graph.generate_graph(self._index, project_name)
            graph.save_graph(g, kb_path)
            self._last_graph_regen = now
            logger.info("watch: regenerated graph")
            return True
        except Exception:
            logger.exception("watch: failed to regenerate graph")
            return False


# =============================================================================
# 独立 daemon 入口
# =============================================================================


def watch_project(
    project_path: Path,
    *,
    poll: bool = False,
    on_indexed: Callable[[str, int], None] | None = None,
) -> Any:  # 返回 watchdog Observer（无类型存根）
    """启动文件监听并返回 Observer（调用方负责运行和停止）。

    Args:
        project_path: 项目根目录
        poll: 使用轮询 Observer（适用于网络文件系统/Docker）
        on_indexed: 每次索引更新后的回调 ``(file_path, chunk_count)``

    Returns:
        已启动的 watchdog Observer
    """
    from code_nearby import config as nearby_config

    kb_path = nearby_config.get_kb_path()
    project_kb_path = storage.ensure_project_kb_path(kb_path, project_path)
    rag_dir = project_kb_path / ".rag"
    rag_dir.mkdir(parents=True, exist_ok=True)

    # 打开索引（不存在则创建）
    idx = RagIndex.open(rag_dir / "index.sqlite3")

    # 如果没有索引，先做一次全量构建
    if AUTO_INITIAL_INDEX and idx.count() == 0:
        logger.info("watch: no index found, running initial full build...")
        from code_nearby.operations.analysis import run_full_analysis

        run_full_analysis(project_path)
        # 重新打开（run_full_analysis 已经 close 了）
        idx = RagIndex.open(rag_dir / "index.sqlite3")

    handler = IndexEventHandler(project_path, idx, rag_dir, on_indexed=on_indexed)
    project_name = project_path.resolve().name

    observer_cls = PollingObserver if poll else Observer
    observer = observer_cls()
    observer.schedule(handler, str(project_path), recursive=True)
    observer.start()

    # 将 main loop 方法附加到 observer 上，供调用方使用
    observer._nearby_handler = handler  # type: ignore[attr-defined]
    observer._nearby_index = idx  # type: ignore[attr-defined]
    observer._nearby_kb_path = project_kb_path  # type: ignore[attr-defined]
    observer._nearby_project_name = project_name  # type: ignore[attr-defined]
    observer._nearby_rag_dir = rag_dir  # type: ignore[attr-defined]

    return observer


def watch_loop(
    project_path: Path,
    *,
    poll: bool = False,
    interval: float = 1.0,
    on_indexed: Callable[[str, int], None] | None = None,
) -> None:
    """启动文件监听并进入阻塞主循环（供 ``nearby watch`` CLI 使用）。

    按 Ctrl+C 优雅退出。
    """
    observer = watch_project(project_path, poll=poll, on_indexed=on_indexed)
    handler = observer._nearby_handler
    idx = observer._nearby_index
    kb_path = observer._nearby_kb_path
    project_name = observer._nearby_project_name

    logger.info("watching %s (poll=%s)...", project_path, poll)
    try:
        while observer.is_alive():
            time.sleep(interval)
            handler.process_pending()
            handler.maybe_regen_graph(project_name, kb_path)
    except KeyboardInterrupt:
        logger.info("watch: stopping...")
    finally:
        observer.stop()
        observer.join(timeout=5)
        idx.close()
