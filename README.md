# brain

A codebase analysis and knowledge management tool with both TUI and CLI interfaces. Automatically analyzes your codebase and generates dependency graphs and structured documentation.

## ✨ Features

- 🔍 **AST-based Analysis** - Extracts functions, classes, type hints, and docstrings
- 📊 **Knowledge Graphs** - Visualize module dependencies
- 🔄 **Incremental Updates** - Only analyzes changed files
- 🔄 **Auto-Sync** - Automatically commit and push knowledge base changes
- 🎨 **TUI Interface** - Beautiful terminal UI with Textual

## 🚀 Quick Start

```bash
# Install uv if needed: https://docs.astral.sh/uv/getting-started/installation/
# Create the virtual environment and install dependencies from uv.lock
uv sync

# Initialize knowledge base
uv run brain init

# Analyze a source Git repository
uv run brain analyze .
# or simply
uv run brain .
```

> 💡 Prefix commands with `uv run` (e.g. `uv run brain analyze .`), or activate the
> environment once with `source .venv/bin/activate` and then call `brain` directly
> (as shown in the Usage section below).

See [Quick Start Guide](./docs/QUICKSTART.md) for detailed instructions.

## 📖 Documentation

- **[Quick Start Guide](./docs/QUICKSTART.md)** - Get started in 5 minutes
- **[Implementation Summary](./docs/IMPLEMENTATION_SUMMARY.md)** - Technical details

## 📁 Knowledge Base Structure

```
~/brain-vault/
└── octocat/
    └── hello-world/
        ├── _GRAPH.json              # 依赖图
        └── .rag/
            └── index.sqlite3        # RAG 索引
```

## 🎯 Use Cases

### 1. Visualize Your Codebase

- Explore module dependency graphs
- Understand relationships between components

### 2. Code Review & Documentation

- Review function signatures and docstrings
- Understand dependencies at a glance
- Track changes over time

### 3. LLM Knowledge Base (Coming Soon)

- MCP Skills integration
- Semantic search
- Code Q&A

## 🛠️ Usage

```bash
brain              # Launch TUI
brain init         # Clone/configure the knowledge base repository
brain status       # Show configuration
brain .            # Analyze current source repository (shortcut for `brain analyze .`)
brain analyze .    # Analyze current source repository
brain analyze --sync  # Analyze and auto-commit/push to knowledge base
brain sync         # Manually sync knowledge base to remote
brain --help       # Show all commands
```

### Synchronization Options

**Auto-sync during analysis:**
```bash
brain analyze . --sync
```
This will analyze your code and automatically commit and push changes to the knowledge base repository.

`brain analyze` reads Git state from the source repository you pass as its target. `brain init`
stores the knowledge base Git repository URL and clones that repository to the configured local
path.

**Manual sync:**
```bash
brain sync
```
Commits and pushes any pending changes in the knowledge base. Useful after manual edits or multiple analyze operations.

## 🧪 Development

```bash
uv sync --extra dev   # Install dev dependencies (pytest, ruff)
uv run pytest         # Run tests
uv run ruff check .   # Lint code
```

## 🏗️ Architecture

- **TUI**: `src/brain/tui.py` - Textual-based interface
- **CLI**: `src/brain/cli.py` - Typer-based commands
- **Analyzer**: `src/brain/analyzer.py` - AST-based code analysis
- **Storage**: `src/brain/storage.py` - Knowledge base I/O
- **Git Utils**: `src/brain/git_utils.py` - Git integration

See [AGENTS.md](./AGENTS.md) for engineering guidelines.

## 🎨 Technology Stack

- **CLI Framework**: [Typer](https://typer.tiangolo.com/)
- **TUI Framework**: [Textual](https://textual.textualize.io/)
- **Analysis**: Python `ast` module
- **Knowledge Base**: Git + RAG (SQLite)

## 🗺️ Roadmap

- [x] Python AST analysis
- [x] Incremental updates
- [x] Auto-sync to knowledge base repository
- [x] Multi-language support (tree-sitter)
- [ ] Function call graph
- [ ] MCP Skills for LLMs
- [ ] Semantic search

## 📄 License

MIT

## 🤝 Contributing

Built with [Typer](https://typer.tiangolo.com/) and [Textual](https://textual.textualize.io/).

Contributions welcome! See [AGENTS.md](./AGENTS.md) for guidelines.
