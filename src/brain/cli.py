"""命令行接口。"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from brain import config
from brain.operations.analysis import run_full_analysis
from brain.operations.config import clear_config

app = typer.Typer(help="Brain - Knowledge Base Manager")


def main() -> None:
    """入口包装，处理 ``brain .`` 快捷方式。"""
    if len(sys.argv) == 2 and sys.argv[1] == ".":
        sys.argv.insert(1, "analyze")
    app()


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    """无子命令时启动 TUI。"""
    if ctx.invoked_subcommand is None:
        from .tui import run as run_tui

        run_tui()


@app.command()
def status() -> None:
    """显示知识库路径。"""
    kb_path = config.get_kb_path()
    typer.echo(f"Knowledge base path: {kb_path}")


@app.command()
def clear() -> None:
    """清除配置（恢复默认值）。"""
    if not typer.confirm("Clear configuration and reset to defaults?", default=False):
        raise typer.Exit(0)

    if clear_config():
        typer.secho("✓ Configuration cleared", fg=typer.colors.GREEN)
    else:
        typer.secho("No configuration to clear", fg=typer.colors.BLUE)


@app.command()
def analyze(
    target: str = typer.Argument(".", help="Path to source directory"),
    full: bool = typer.Option(False, "--full", help="Force full rebuild"),
    kb_name: str = typer.Option(
        None, "--kb-name", help="Explicit knowledge base name (avoids directory name conflicts)"
    ),
) -> None:
    """分析源码目录——产出 RAG 检索索引 + 依赖图。

    一次变更检测 + 共享 CST 遍历，产出 SQLite FTS5 检索索引和
    ``_GRAPH.json`` 依赖图。仅分析变更文件，除非指定 --full。
    """
    target_path = Path(target).resolve()
    if not target_path.is_dir():
        typer.secho(f"✗ Not a directory: {target_path}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo(f"Analyzing {target_path}...")
    result = run_full_analysis(target_path, full_rebuild=full, kb_name=kb_name)

    if result["success"]:
        typer.secho(
            f"✓ Analyzed {result['files_analyzed']} files "
            f"({result['added']} added, {result['modified']} modified, "
            f"{result['deleted']} deleted) — "
            f"{result['chunks_total']} RAG chunks indexed",
            fg=typer.colors.GREEN,
        )
        if kb_location := result.get("kb_path"):
            typer.echo(f"Knowledge base: {kb_location}")
    else:
        typer.secho(f"✗ {result['error']}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (identifier, API name, or keywords)"),
    max_results: int = typer.Option(5, "--max", "-k", help="Maximum number of results"),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON output"),
    lang: str = typer.Option(None, "--lang", help="Filter by language (e.g. python)"),
    path: str = typer.Option(None, "--path", help="Filter by file-path glob (e.g. src/**/*.py)"),
    budget: int = typer.Option(None, "--budget", help="Token budget for assembled context"),
    project: str = typer.Option(None, "--project", "-p", help="Project path (default: cwd)"),
    kb_name: str = typer.Option(
        None, "--kb-name", help="Knowledge base name (must match analyze --kb-name)"
    ),
) -> None:
    """检索词汇+结构索引，返回相关代码 chunk。

    运行 BM25 + symbol (trigram) 召回，RRF 融合，依赖图加分，
    返回带 file:line 引用的 token 预算感知结果。
    需先运行 'brain analyze'。
    """
    kb_path = config.get_kb_path()
    project_path = Path(project).resolve() if project else Path.cwd().resolve()

    from brain import storage

    project_kb_path = storage.get_project_kb_path(kb_path, project_path, kb_name=kb_name)
    index_file = project_kb_path / ".rag" / "index.sqlite3" if project_kb_path else None
    if index_file is None or not index_file.exists():
        typer.secho(
            f"⚠ No search index for project: {project_path.name}",
            fg=typer.colors.YELLOW,
        )
        typer.echo("Run 'brain analyze' first to build the search index.")
        raise typer.Exit(1)

    import json as _json

    from brain.rag import assemble as rag_assemble
    from brain.rag import retrieve as rag_retrieve
    from brain.rag.index import RagIndex

    index = RagIndex.open(index_file)
    try:
        scored = rag_retrieve.search(
            index,
            query,
            k=max_results,
            language=lang,
            path_glob=path,
            graph=rag_retrieve.load_graph(project_kb_path),
        )
        payload = rag_assemble.assemble(query, scored, budget=budget)
    finally:
        index.close()

    if json_output:
        typer.echo(_json.dumps(payload, indent=2, ensure_ascii=False))
        return

    results = payload["results"]
    if not results:
        typer.secho(f"No results found for: {query}", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    typer.secho(f"\nFound {len(results)} result(s) for '{query}':\n", fg=typer.colors.BLUE)
    for item in results:
        typer.secho(f"{item['rank']}. {item['ref']}", fg=typer.colors.WHITE, bold=True)
        typer.secho(
            f"   {item['type']} {item['qualified_name']} | score {item['score']:.4f}",
            fg=typer.colors.CYAN,
        )
        if item["signature"]:
            typer.echo(f"   {item['signature']}")
        typer.echo()
    if payload["truncated"]:
        typer.secho("   (truncated to fit token budget)", fg=typer.colors.BRIGHT_BLACK)
