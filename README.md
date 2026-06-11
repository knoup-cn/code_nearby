# brain

A dual-mode knowledge management tool with both TUI and CLI interfaces.

## Quick Start (No Installation)

### TUI Mode (Interactive)

```bash
python -m brain
```

### CLI Mode (Commands)

```bash
python -m brain init
python -m brain status
python -m brain --help
```

## Installation (Optional)

For system-wide access:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then use the `brain` command directly:

```bash
brain          # Launch TUI
brain init     # CLI commands
brain status
```

Built with [Typer](https://typer.tiangolo.com/) for type-safe CLI development.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```
