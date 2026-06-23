"""Brain MCP Server — 将 brain 代码检索引擎暴露为 LLM 可调用的 MCP 工具。

基于 Model Context Protocol (MCP) 的 stdio 传输，提供代码搜索、
文件概览、项目符号索引和模块上下文扩展等工具。

启动时自动拉起 watchdog 实时监听文件变更并增量更新索引，
无需额外运行 ``brain watch``。可通过环境变量 ``BRAIN_WATCHDOG=0`` 禁用。

Usage::

    uv run brain-mcp [--project /path/to/project]
    # 或
    python -m brain.mcp_server [--project /path/to/project]

跨项目配置 —— 推荐方式：

**方案 1（推荐）：每项目独立配置**

在目标项目的 ``.claude/settings.json`` 中添加::

    {
      "mcpServers": {
        "brain": {
          "command": "uv",
          "args": ["run", "--project", "/path/to/brain/repo", "brain-mcp"]
        }
      }
    }

Claude Code 会自动将 ``cwd`` 设为该项目的根目录，brain 就能索引该项目。

**方案 2：全局配置 + cwd 指定**

在 ``~/.claude/settings.json`` 中::

    {
      "mcpServers": {
        "brain": {
          "command": "uv",
          "args": ["run", "--project", "/path/to/brain/repo", "brain-mcp"],
          "cwd": "/path/to/target/project"
        }
      }
    }

缺点：全局只能指定一个固定 ``cwd``，切换项目需手动改配置。
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Any

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from brain import config, storage
from brain.rag import assemble, retrieve
from brain.rag.context import expand_module_context, load_context_graph
from brain.rag.index import OldSchemaError, RagIndex

logger = logging.getLogger(__name__)

server = Server("brain")

# =============================================================================
# watchdog 集成 —— 实时增量索引
# =============================================================================

_watch_observer: Any = None
_watch_handler: Any = None
_watch_index: RagIndex | None = None
_watch_kb_path: Path | None = None
_watch_project_name: str | None = None
_watch_project_root: Path | None = None

_WATCHDOG_AVAILABLE = False
try:
    from brain.watch import watch_project

    _WATCHDOG_AVAILABLE = True
except ImportError:
    pass


def _watchdog_disabled() -> bool:
    """检查环境变量是否显式禁用 watchdog。"""
    return os.environ.get("BRAIN_WATCHDOG", "").strip() == "0"


def _start_watchdog(project_path: Path) -> None:
    """启动文件监听 Observer（同步调用，阻塞至初始索引构建完成）。"""
    global _watch_observer, _watch_handler, _watch_index
    global _watch_kb_path, _watch_project_name, _watch_project_root

    _watch_project_root = project_path
    observer = watch_project(project_path)
    _watch_observer = observer
    _watch_handler = observer._brain_handler
    _watch_index = observer._brain_index
    _watch_kb_path = observer._brain_kb_path
    _watch_project_name = observer._brain_project_name

    logger.info(
        "mcp: watchdog started — %d files, %d chunks",
        len(_watch_index.list_files()) if _watch_index else 0,
        _watch_index.count() if _watch_index else 0,
    )


async def _watchdog_tick() -> None:
    """后台协程：每秒处理已就绪的文件变更 + 定期更新依赖图。"""
    while _watch_observer is not None and _watch_observer.is_alive():
        await anyio.sleep(1)
        if _watch_handler is not None:
            try:
                _watch_handler.process_pending()
            except Exception:
                logger.exception("watchdog: process_pending error")
        if (
            _watch_handler is not None
            and _watch_kb_path is not None
            and _watch_project_name is not None
        ):
            try:
                _watch_handler.maybe_regen_graph(_watch_project_name, _watch_kb_path)
            except Exception:
                logger.exception("watchdog: maybe_regen_graph error")


def _stop_watchdog() -> None:
    """停止文件监听并关闭索引。"""
    global _watch_observer, _watch_handler, _watch_index
    global _watch_kb_path, _watch_project_name, _watch_project_root

    if _watch_observer is not None:
        _watch_observer.stop()
        _watch_observer.join(timeout=5)
        _watch_observer = None
        logger.info("mcp: watchdog stopped")

    if _watch_index is not None:
        with contextlib.suppress(Exception):
            _watch_index.close()
        _watch_index = None

    _watch_handler = None
    _watch_kb_path = None
    _watch_project_name = None
    _watch_project_root = None

# --- helpers -----------------------------------------------------------------


def _owns_index(idx: RagIndex) -> bool:
    """检查此索引连接是否由 watchdog 管理（调用方不应关闭）。"""
    return _watch_index is not None and idx is _watch_index


def _resolve_project(project_path: str | None) -> Path:
    """解析项目路径：优先参数，回退到当前目录。"""
    return Path(project_path).resolve() if project_path else Path.cwd().resolve()


def _get_index(project_path: Path) -> tuple[RagIndex, Path]:
    """打开项目 RAG 索引。

    优先复用 watchdog 已打开的索引连接（免去重复 open/close）；
    若 watchdog 未在监听此项目，则回退到独立打开（含自动构建逻辑）。

    Returns:
        (index, project_kb_path)
    """
    # watchdog 正在监听此项目 → 复用其索引连接
    if (
        _watch_index is not None
        and _watch_project_root is not None
        and _watch_project_root == project_path
        and _watch_kb_path is not None
    ):
        return _watch_index, _watch_kb_path

    # 回退：独立打开索引
    from brain.operations.analysis import run_full_analysis

    kb_path = config.get_kb_path()
    project_kb_path = storage.get_project_kb_path(kb_path, project_path)
    if project_kb_path is None:
        raise RuntimeError(f"Cannot determine knowledge base path for {project_path}")
    index_file = project_kb_path / ".rag" / "index.sqlite3"

    if not index_file.exists():
        logger.info("mcp: no index found, auto-building for %s ...", project_path.name)
        result = run_full_analysis(project_path)
        if not result["success"]:
            raise RuntimeError(f"Auto-index failed: {result['error']}")
        logger.info(
            "mcp: index built — %d chunks across %d files",
            result["chunks_total"],
            result["files_analyzed"],
        )

    idx = RagIndex.open(index_file)
    return idx, project_kb_path


def _chunk_to_text(chunk_dict: dict[str, Any]) -> str:
    """单条检索结果的 Markdown 格式化。"""
    lines = [
        f"### [{chunk_dict['rank']}] {chunk_dict['qualified_name']} ({chunk_dict['type']})",
        f"- **File**: `{chunk_dict['ref']}`",
        f"- **Lines**: {chunk_dict['lines']}",
        f"- **Score**: {chunk_dict['score']:.4f}",
        f"- **Language**: {chunk_dict['language']}",
    ]
    if chunk_dict.get("context_window"):
        lines.append(f"- **Context window**: {chunk_dict['context_window']}")
    lines.append("")
    lines.append("```" + chunk_dict["language"])
    lines.append(chunk_dict["content"].rstrip())
    lines.append("```")
    return "\n".join(lines)


# --- MCP tools ---------------------------------------------------------------


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="brain_search",
            description=(
                "Search code in the project using BM25 + trigram lexical retrieval. "
                "Best for finding exact symbols (function names, class names), API usage, "
                "and keyword patterns. Supports language and path filtering. "
                "Returns structured code snippets with file:line references and context windows."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query — identifier, symbol, API name, or keywords",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results (default 5, max 20)",
                        "default": 5,
                    },
                    "language": {
                        "type": "string",
                        "description": "Filter by language (e.g. 'python', 'typescript')",
                    },
                    "path_glob": {
                        "type": "string",
                        "description": "Filter by file path glob (e.g. 'src/**/*.py')",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project path (default: current directory)",
                    },
                    "window": {
                        "type": "string",
                        "description": "Context window: none, minimal, moderate, generous",
                        "default": "moderate",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="brain_file_info",
            description=(
                "List all symbols (functions, classes, methods) in a specific file. "
                "Use this to understand a file's structure before diving into specific symbols."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File path relative to project root (e.g. 'src/auth.py')",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project path (default: current directory)",
                    },
                },
                "required": ["file_path"],
            },
        ),
        types.Tool(
            name="brain_project_symbols",
            description=(
                "Get a project-wide summary of all top-level symbols (functions, classes) "
                "with their file locations. Use for project orientation, finding entry points, "
                "or understanding codebase structure."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "Optional language filter (e.g. 'python')",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project path (default: current directory)",
                    },
                },
            },
        ),
        types.Tool(
            name="brain_module_context",
            description=(
                "Given a file path, return the dependency context: which modules it imports, "
                "and key symbols from those dependent modules. Uses the dependency graph "
                "generated during 'brain analyze'. Essential for understanding module dependencies."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File path relative to project root (e.g. 'src/auth.py')",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project path (default: current directory)",
                    },
                },
                "required": ["file_path"],
            },
        ),
        types.Tool(
            name="brain_status",
            description=(
                "Show brain index status for the current project: number of indexed chunks, "
                "files tracked, and knowledge base location."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project path (default: current directory)",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    project_root = _resolve_project(arguments.get("project"))

    if name == "brain_search":
        return await _search(arguments, project_root)
    elif name == "brain_file_info":
        return await _file_info(arguments, project_root)
    elif name == "brain_project_symbols":
        return await _project_symbols(arguments, project_root)
    elif name == "brain_module_context":
        return await _module_context(arguments, project_root)
    elif name == "brain_status":
        return await _status(project_root)
    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


# --- tool implementations ----------------------------------------------------


async def _search(args: dict[str, Any], project_root: Path) -> list[types.TextContent]:
    query = args["query"]
    max_results = min(args.get("max_results", 5), 20)
    language = args.get("language")
    path_glob = args.get("path_glob")
    window = args.get("window", "moderate")

    try:
        idx, project_kb_path = _get_index(project_root)
    except RuntimeError as e:
        return [types.TextContent(type="text", text=str(e))]

    try:
        scored = retrieve.search(
            idx,
            query,
            k=max_results,
            language=language,
            path_glob=path_glob,
            graph=retrieve.load_graph(project_kb_path),
        )
        payload = assemble.assemble(
            query,
            scored,
            project_root=project_root,
            window_strategy=window,
        )
    finally:
        if not _owns_index(idx):
            idx.close()

    results = payload["results"]
    if not results:
        return [types.TextContent(type="text", text=f"No results found for: {query}")]

    parts: list[str] = [
        f"Found {len(results)} result(s) for '{query}'",
    ]
    if payload.get("skipped"):
        parts.append(f"({payload['skipped']} result(s) skipped — source file not found)")
    if payload["truncated"]:
        parts.append("(truncated to fit token budget)")
    parts.append("")

    for r in results:
        parts.append(_chunk_to_text(r))

    return [types.TextContent(type="text", text="\n".join(parts))]


async def _file_info(args: dict[str, Any], project_root: Path) -> list[types.TextContent]:
    file_path = args["file_path"]

    try:
        idx, _ = _get_index(project_root)
    except RuntimeError as e:
        return [types.TextContent(type="text", text=str(e))]

    try:
        symbols = idx.get_file_symbols(file_path)
        imports = idx.get_file_imports(file_path)
    finally:
        if not _owns_index(idx):
            idx.close()

    if not symbols:
        return [types.TextContent(type="text", text=f"No indexed symbols found in: {file_path}")]

    lines: list[str] = [
        f"## {file_path}",
        f"**{len(symbols)} symbols** indexed",
    ]
    if imports:
        lines.append(f"**Imports**: {', '.join(imports[:20])}")
    lines.append("")

    for s in symbols:
        sig = s["signature"][:100] if s["signature"] else ""
        lines.append(
            f"- `{s['qualified_name']}` ({s['chunk_type']}) "
            f"line {s['start_line']} — {sig}"
        )

    return [types.TextContent(type="text", text="\n".join(lines))]


async def _project_symbols(args: dict[str, Any], project_root: Path) -> list[types.TextContent]:
    language = args.get("language")

    try:
        idx, _ = _get_index(project_root)
    except RuntimeError as e:
        return [types.TextContent(type="text", text=str(e))]

    try:
        symbols = idx.get_project_symbols(language=language)
        files = idx.list_files()
        total = idx.count()
    finally:
        if not _owns_index(idx):
            idx.close()

    lines: list[str] = [
        f"## Project: {project_root.name}",
        f"**{len(files)} files** indexed, **{total} chunks** total, **{len(symbols)} symbols**",
    ]
    if language:
        lines[1] += f" (filtered: {language})"
    lines.append("")

    # 按文件分组
    by_file: dict[str, list[dict]] = {}
    for s in symbols:
        by_file.setdefault(s["file_path"], []).append(s)

    for file_path, syms in sorted(by_file.items()):
        lines.append(f"### {file_path} ({len(syms)} symbols)")
        for s in syms[:20]:  # 每个文件最多 20 个
            lines.append(f"  - `{s['qualified_name']}` ({s['chunk_type']}:{s['start_line']})")
        if len(syms) > 20:
            lines.append(f"  - ... and {len(syms) - 20} more")
        lines.append("")

    return [types.TextContent(type="text", text="\n".join(lines))]


async def _module_context(args: dict[str, Any], project_root: Path) -> list[types.TextContent]:
    file_path = args["file_path"]

    try:
        idx, project_kb_path = _get_index(project_root)
    except RuntimeError as e:
        return [types.TextContent(type="text", text=str(e))]

    try:
        graph = load_context_graph(project_kb_path)
        if graph is None:
            return [
                types.TextContent(
                    type="text",
                    text="No dependency graph found. Run 'brain analyze' first.",
                )
            ]

        from brain.rag.context import graph_module_name

        module_name = graph_module_name(graph, file_path)
        imports = idx.get_file_imports(file_path)

        lines: list[str] = [
            f"## Module Context: {module_name or file_path}",
        ]

        if imports:
            lines.append(f"**Imports**: {', '.join(imports[:30])}")
        lines.append("")

        # 获取此文件的一个代表 chunk 用于图扩展
        module_chunks = idx.get_chunks([f"{file_path}::<module>"])
        if module_chunks:
            related = expand_module_context(module_chunks[0], graph, idx)
        else:
            # 获取第一个 function/class chunk
            symbols = idx.get_file_symbols(file_path)
            if symbols:
                first_qname = symbols[0]["qualified_name"]
                first_cid = f"{file_path}::{first_qname}"
                chunks = idx.get_chunks([first_cid])
                related = expand_module_context(chunks[0], graph, idx) if chunks else []
            else:
                related = []

        if related:
            lines.append("### 依赖模块代表符号")
            for c in related:
                lines.append(
                    f"- `{c.qualified_name}` ({c.chunk_type}) "
                    f"in `{c.file_path}:{c.start_line}` — {c.signature[:120]}"
                )
        else:
            lines.append("_(no dependency context available)_")

    finally:
        if not _owns_index(idx):
            idx.close()

    return [types.TextContent(type="text", text="\n".join(lines))]


async def _status(project_root: Path) -> list[types.TextContent]:
    # 优先复用 watchdog 索引（无需额外打开）
    if _watch_index is not None and _watch_project_root == project_root:
        count = _watch_index.count()
        files = len(_watch_index.list_files())
        status_line = (
            f"**Project**: {project_root.name}\n"
            f"**Index**: {count} chunks across {files} files\n"
            f"**KB path**: {_watch_kb_path}\n"
            f"**Watchdog**: active"
        )
        return [types.TextContent(type="text", text=status_line)]

    kb_path = config.get_kb_path()
    project_kb_path = storage.get_project_kb_path(kb_path, project_root)
    index_file = project_kb_path / ".rag" / "index.sqlite3" if project_kb_path else None

    if index_file and index_file.exists():
        try:
            idx = RagIndex.open(index_file)
            count = idx.count()
            files = len(idx.list_files())
            idx.close()
            status_line = (
                f"**Project**: {project_root.name}\n"
                f"**Index**: {count} chunks across {files} files\n"
                f"**KB path**: {project_kb_path}"
            )
        except OldSchemaError:
            status_line = (
                f"**Project**: {project_root.name}\n"
                f"**Status**: Old index schema — run 'brain analyze --full' to rebuild\n"
                f"**KB path**: {project_kb_path}"
            )
    else:
        status_line = (
            f"**Project**: {project_root.name}\n"
            f"**Status**: No index — run 'brain analyze' first\n"
            f"**KB path**: {project_kb_path}"
        )

    return [types.TextContent(type="text", text=status_line)]


# --- entry point -------------------------------------------------------------


async def _main() -> None:
    project_root = Path.cwd().resolve()

    # 启动 watchdog（同步，阻塞至初始索引就绪）
    if _WATCHDOG_AVAILABLE and not _watchdog_disabled():
        try:
            _start_watchdog(project_root)
        except Exception:
            logger.exception("mcp: watchdog failed to start, continuing without it")

    async with anyio.create_task_group() as tg:
        # watchdog 后台 tick 协程
        if _watch_handler is not None:
            tg.start_soon(_watchdog_tick)

        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

        # stdio 关闭 → 停止 tick 协程
        tg.cancel_scope.cancel()

    # 清理
    if _watch_observer is not None:
        _stop_watchdog()


def run() -> None:
    """MCP server stdio 入口。"""
    with contextlib.suppress(KeyboardInterrupt):
        anyio.run(_main)


if __name__ == "__main__":
    run()
