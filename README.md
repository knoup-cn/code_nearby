# brain

A dual-mode knowledge management tool with both TUI and CLI interfaces. Automatically analyzes your codebase and generates **Obsidian-friendly** documentation with wikilinks, metadata, and visual knowledge graphs.

## ✨ Features

- 🔍 **AST-based Analysis** - Extracts functions, classes, type hints, and docstrings
- 🔗 **Obsidian Integration** - Generates wikilinks for seamless navigation
- 📊 **Knowledge Graphs** - Visualize module dependencies in Obsidian
- 🏷️ **Smart Tagging** - Auto-infers tags based on content and location
- 📈 **Dataview Queries** - Query your codebase with SQL-like syntax
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
- **[Obsidian Integration](./docs/OBSIDIAN_INTEGRATION.md)** - Advanced Obsidian features
- **[Implementation Summary](./docs/IMPLEMENTATION_SUMMARY.md)** - Technical details

## 📁 Knowledge Base Structure

```
~/brain-vault/
└── octocat/
    └── hello-world/
        ├── _PROJECT.md              # 项目总览（MOC）
        ├── _MODULES.md              # 模块索引
        └── src/
            └── module.md            # 模块文档（带 wikilinks）
```

Each module document includes:
- **Frontmatter** - Structured metadata (tags, exports, LOC)
- **Wikilinks** - `[[internal_module]]` links for navigation
- **Type Signatures** - Full function signatures with type hints
- **Dependencies** - Internal and external dependencies
- **Callouts** - Beautiful Obsidian callouts for docs

## 🎯 Use Cases

### 1. Visualize Your Codebase in Obsidian

- Open knowledge base in Obsidian
- Use Graph View to see module relationships
- Click wikilinks to navigate between modules

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

## 🔬 Example Output

### Generated Module Documentation

```markdown
---
type: python-module
path: src/brain/analyzer.py
project: "[[_PROJECT]]"
tags: [python, core]
dependencies:
  - "[[storage]]"
  - "[[git_utils]]"
exports:
  - analyze_file
lines_of_code: 248
---

# analyzer

> [!info] Module Purpose
> Code analysis operations.

## Public API

### `analyze_file(file_path: Path, kb_path: Path, project_root: Path) -> None`

**Location**: `src/brain/analyzer.py:11`

> [!example] Documentation
> Analyze a single file and write to knowledge base.

## Dependencies

**Internal**:
- [[storage]]
- [[git_utils]]

---

**Navigation**: [[_PROJECT]] • [[_MODULES]]
```

## 🔍 Obsidian Dataview Queries

Query your codebase with SQL-like syntax:

```dataview
TABLE type, lines_of_code, length(exports) AS "Exports"
FROM #python
SORT lines_of_code DESC
```

```dataview
LIST
FROM [[analyzer]]
SORT file.name
```

See [Obsidian Integration Guide](./docs/OBSIDIAN_INTEGRATION.md) for more examples.

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
- **Knowledge Base**: Git + Markdown + YAML Frontmatter

## 🗺️ Roadmap

- [x] Python AST analysis
- [x] Obsidian wikilinks
- [x] MOC index generation
- [x] Incremental updates
- [x] Auto-sync to knowledge base repository
- [ ] Multi-language support (tree-sitter)
- [ ] Function call graph
- [ ] MCP Skills for LLMs
- [ ] Semantic search

## 📄 License

MIT

## 🤝 Contributing

Built with [Typer](https://typer.tiangolo.com/) and [Textual](https://textual.textualize.io/).

Contributions welcome! See [AGENTS.md](./AGENTS.md) for guidelines.
