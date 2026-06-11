"""Command-line interface."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

from brain import operations

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
    status = operations.get_status()
    if status:
        typer.secho("Already initialized.", fg=typer.colors.BLUE)
        if not typer.confirm("Reconfigure?"):
            raise typer.Exit(0)

    while True:
        vault_path = typer.prompt("Local path", default=str(Path.home() / "brain-vault"))
        git_repo = typer.prompt("Git repository URL")

        target = Path(vault_path).expanduser().resolve()
        overwrite = False

        if target.exists() and any(target.iterdir()):
            typer.secho(f"⚠ Directory not empty: {target}", fg=typer.colors.YELLOW)
            if not typer.confirm("Overwrite?", default=False):
                continue
            overwrite = True

        success, msg = operations.init_config(git_repo, target, overwrite)

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
    cfg = operations.get_status()
    if not cfg:
        typer.secho("⚠ Not initialized. Run 'brain init'", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    typer.echo(f"Git repo: {cfg.get('git_repo', 'N/A')}")
    typer.echo(f"Local path: {cfg.get('local_path', 'N/A')}")


@app.command()
def clear() -> None:
    """Clear configuration."""
    if not operations.get_status():
        typer.secho("Not initialized.", fg=typer.colors.BLUE)
        raise typer.Exit(0)

    if not typer.confirm("Clear configuration?", default=False):
        raise typer.Exit(0)

    operations.clear_config()
    typer.secho("✓ Cleared", fg=typer.colors.GREEN)


@app.command()
def analyze(
    target: str = typer.Argument(".", help="Path to Git repository"),
    full: bool = typer.Option(False, "--full", help="Force full rebuild"),
) -> None:
    """Analyze Git repository and update knowledge base.

    Analyzes code in a Git repository incrementally and stores results
    in the configured knowledge base. Only changed files are re-analyzed
    unless --full is specified.
    """
    target_path = Path(target).resolve()

    # Validate Git repository
    if not operations.is_git_repo(target_path):
        typer.secho(f"✗ Not a Git repository: {target_path}", fg=typer.colors.RED)
        typer.echo("Initialize with: git init")
        raise typer.Exit(1)

    # Validate knowledge base initialized
    cfg = operations.get_status()
    if not cfg:
        typer.secho("⚠ Run 'brain init' first", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    # Execute analysis
    typer.echo(f"Analyzing {target_path}...")
    result = operations.analyze_project(target_path, full_rebuild=full)

    # Output result
    if result["success"]:
        typer.secho(
            f"✓ Analyzed {result['files_analyzed']} files "
            f"({result['added']} added, {result['modified']} modified, "
            f"{result['deleted']} deleted)",
            fg=typer.colors.GREEN,
        )
    else:
        typer.secho(f"✗ {result['error']}", fg=typer.colors.RED)
        raise typer.Exit(1)

