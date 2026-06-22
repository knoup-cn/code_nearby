"""Command-line interface."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from brain.operations.analysis import run_full_analysis
from brain.operations.config import (
    clear_config,
    get_status,
    init_config,
    is_git_repo,
    needs_overwrite,
)
from brain.operations.sync import sync_knowledge_base

app = typer.Typer(help="Brain - Knowledge Base Manager")


def main() -> None:
    """Entry point wrapper to handle `brain .` shortcut."""
    # Transform `brain .` → `brain analyze .`
    if len(sys.argv) == 2 and sys.argv[1] == ".":
        sys.argv.insert(1, "analyze")
    app()


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    """Launch TUI if no command specified."""
    if ctx.invoked_subcommand is None:
        from .tui import run as run_tui

        run_tui()


@app.command()
def init() -> None:
    """Initialize knowledge base."""
    status = get_status()
    if status:
        typer.secho("Already initialized.", fg=typer.colors.BLUE)
        if not typer.confirm("Reconfigure?"):
            raise typer.Exit(0)

    while True:
        kb_local_path = typer.prompt(
            "Knowledge base local path",
            default=str(Path.home() / "brain-vault"),
        )
        kb_git_repo = typer.prompt("Knowledge base Git repository URL")

        target = Path(kb_local_path).expanduser().resolve()
        overwrite = False

        if needs_overwrite(target):
            typer.secho(f"⚠ Directory not empty: {target}", fg=typer.colors.YELLOW)
            if not typer.confirm("Overwrite?", default=False):
                continue
            overwrite = True

        success, msg = init_config(kb_git_repo, target, overwrite)

        if success:
            typer.secho(f"✓ {msg}", fg=typer.colors.GREEN)
            break
        else:
            typer.secho(f"✗ {msg}", fg=typer.colors.RED)
            if not typer.confirm("Retry?"):
                raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show configuration status."""
    cfg = get_status()
    if not cfg:
        typer.secho("⚠ Not initialized. Run 'brain init'", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    typer.echo(f"Knowledge base Git repo: {cfg.get('git_repo', 'N/A')}")
    typer.echo(f"Knowledge base local path: {cfg.get('local_path', 'N/A')}")


@app.command()
def clear() -> None:
    """Clear configuration."""
    if not get_status():
        typer.secho("Not initialized.", fg=typer.colors.BLUE)
        raise typer.Exit(0)

    if not typer.confirm("Clear configuration?", default=False):
        raise typer.Exit(0)

    clear_config()
    typer.secho("✓ Cleared", fg=typer.colors.GREEN)


@app.command()
def analyze(
    target: str = typer.Argument(".", help="Path to source Git repository"),
    full: bool = typer.Option(False, "--full", help="Force full rebuild"),
    sync: bool = typer.Option(False, "--sync", help="Commit and push changes to knowledge base"),
) -> None:
    """Analyze source repository — produces RAG search index + dependency graph.

    Detects changes once, generates a SQLite FTS5 search index and a
    ``_GRAPH.json`` dependency graph in a single pass.
    Only changed files are re-analyzed unless --full is specified.

    Use --sync to automatically commit and push changes to the knowledge
    base repository after analysis.
    """
    target_path = Path(target).resolve()

    if not is_git_repo(target_path):
        typer.secho(f"✗ Not a source Git repository: {target_path}", fg=typer.colors.RED)
        typer.echo("Initialize with: git init")
        raise typer.Exit(1)

    cfg = get_status()
    if not cfg:
        typer.secho("⚠ Run 'brain init' first", fg=typer.colors.YELLOW)
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

        if sync and result["files_analyzed"] > 0:
            from brain.operations.sync import sync_knowledge_base

            changes_summary = (
                f"{result['added']} added, {result['modified']} modified, "
                f"{result['deleted']} deleted"
            )
            sync_result = sync_knowledge_base(
                Path(cfg["local_path"]), target_path, changes_summary=changes_summary
            )
            if sync_result["success"]:
                commit = sync_result.get("commit")
                if commit:
                    typer.secho(
                        f"✓ Committed to knowledge base: {commit[:8]}",
                        fg=typer.colors.GREEN,
                    )
                if sync_result.get("pushed"):
                    typer.secho("✓ Pushed to remote", fg=typer.colors.GREEN)
                else:
                    typer.secho("⚠ Push failed", fg=typer.colors.YELLOW)
            else:
                typer.secho(f"✗ Sync failed: {sync_result.get('error')}", fg=typer.colors.RED)
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
) -> None:
    """Search the lexical+structural index for relevant code chunks.

    Runs BM25 + symbol (trigram) recall, fuses with RRF, applies a dependency
    graph boost, and returns token-budgeted chunks with file:line citations.
    Requires 'brain analyze' to have been run for the project.

    Examples:
        brain search analyze_file
        brain search "fetch remote url" --json --budget 2000
        brain search load --lang python --path 'src/**/*.py'
    """
    if not get_status():
        typer.secho("⚠ Run 'brain init' first", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    cfg = get_status()
    kb_path = Path(cfg["local_path"])
    project_path = Path(project).resolve() if project else Path.cwd().resolve()

    from brain import storage

    project_kb_path = storage.get_project_kb_path(kb_path, project_path)
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


@app.command()
def sync() -> None:
    """Commit and push knowledge base changes to remote repository.

    Commits any pending changes in the knowledge base and pushes them
    to the remote repository. Useful when you've made manual edits or
    want to sync after multiple analyze operations.
    """
    # Validate knowledge base initialized
    cfg = get_status()
    if not cfg:
        typer.secho("⚠ Run 'brain init' first", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    kb_path = Path(cfg["local_path"])

    # Check if KB is a git repository
    if not is_git_repo(kb_path):
        typer.secho(f"✗ Knowledge base is not a git repository: {kb_path}", fg=typer.colors.RED)
        raise typer.Exit(1)

    # Check for changes
    from brain import git_utils

    if not git_utils.has_changes(kb_path):
        typer.secho("✓ Knowledge base is up to date", fg=typer.colors.BLUE)
        raise typer.Exit(0)

    # Show status
    status = git_utils.get_repo_status(kb_path)
    total_changes = sum(len(v) for v in status.values())
    typer.echo(f"Changes detected: {total_changes} files")

    # Confirm
    if not typer.confirm("Commit and push changes?", default=True):
        raise typer.Exit(0)

    # Perform sync
    typer.echo("Syncing knowledge base...")
    result = sync_knowledge_base(kb_path, kb_path, changes_summary=f"{total_changes} files")

    if result["success"]:
        commit = result.get("commit")
        if commit:
            typer.secho(f"✓ Committed: {commit[:8]}", fg=typer.colors.GREEN)
        if result.get("pushed"):
            typer.secho("✓ Pushed to remote", fg=typer.colors.GREEN)
        else:
            typer.secho("⚠ Push failed", fg=typer.colors.YELLOW)
            if error := result.get("error"):
                typer.echo(f"Error: {error}")
            typer.echo("Run 'git push' manually in the knowledge base directory")
    else:
        typer.secho(f"✗ Sync failed: {result.get('error')}", fg=typer.colors.RED)
        raise typer.Exit(1)
