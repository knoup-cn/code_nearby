"""命令行接口 — 最小 CLI，核心功能走 MCP。"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from code_nearby import config
from code_nearby.operations.analysis import run_full_analysis

app = typer.Typer(help="Code Nearby — MCP server for codebase context")


def main() -> None:
    """入口包装，处理 ``nearby .`` 快捷方式。"""
    if len(sys.argv) == 2 and sys.argv[1] == ".":
        sys.argv.insert(1, "analyze")
    app()


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    """无子命令时显示简介。"""
    if ctx.invoked_subcommand is None:
        typer.echo(
            "Code Nearby — MCP server for codebase context\n"
            "\n"
            "Configure in your MCP client (e.g. .claude/settings.json):\n"
            '  {"mcpServers": {"nearby": {"command": "uv", "args": ["run", "nearby-mcp"]}}}\n'
            "\n"
            "CLI commands:\n"
            "  nearby analyze .    Build RAG index for a project\n"
            "  nearby status       Show knowledge base path\n"
            "\n"
            "Docs: https://github.com/knoup/code-nearby"
        )


@app.command()
def status() -> None:
    """显示知识库路径。"""
    kb_path = config.get_kb_path()
    typer.echo(f"Knowledge base path: {kb_path}")


@app.command()
def analyze(
    target: str = typer.Argument(".", help="Path to source directory"),
    full: bool = typer.Option(False, "--full", help="Force full rebuild"),
) -> None:
    """分析源码目录——产出 RAG 检索索引 + 依赖图。"""
    target_path = Path(target).resolve()
    if not target_path.is_dir():
        typer.secho(f"✗ Not a directory: {target_path}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo(f"Analyzing {target_path}...")
    result = run_full_analysis(target_path, full_rebuild=full)

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
