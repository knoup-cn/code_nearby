# Code Nearby

**Give your LLM the context it needs — right next to your code.**

Code Nearby is an MCP server that indexes your codebase and gives AI assistants the ability to search, explore, and understand your project. Think of it as giving Claude Code (or any MCP-compatible client) a map of everything **nearby** your code: symbols, dependencies, imports, and the code itself.

## Why Code Nearby?

LLMs are powerful, but they're blind to your codebase. You end up copy-pasting files, explaining architecture, and repeating yourself. Code Nearby solves this by:

- **Indexing** your project into a fast SQLite FTS5 + symbol search engine
- **Exposing** the index as MCP tools (`nearby_search`, `nearby_file_info`, etc.)
- **Auto-updating** via file watching (watchdog) — no manual re-indexing

## Quick Start

### 1. Install

```bash
pip install code-nearby[mcp]
# or with uv:
uv add code-nearby --extra mcp
```

### 2. Configure MCP Client

Add to your Claude Code `.claude/settings.json`:

```json
{
  "mcpServers": {
    "nearby": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/code-nearby/repo", "nearby-mcp"]
    }
  }
}
```

Or use the CLI to pre-build the index:

```bash
nearby analyze .
```

### 3. Start Chatting

Your LLM can now:
- `nearby_search` — find symbols, APIs, keywords in your codebase
- `nearby_file_info` — list all symbols in a file
- `nearby_project_symbols` — browse the project symbol tree
- `nearby_module_context` — see what a module imports and connects to
- `nearby_status` — check index health

## MCP Tools

| Tool | Description |
|------|-------------|
| `nearby_search` | BM25 + trigram code search with language/path filters |
| `nearby_file_info` | List symbols (functions, classes) in a file |
| `nearby_project_symbols` | Project-wide symbol summary |
| `nearby_module_context` | Dependency context for a module |
| `nearby_status` | Index status & statistics |

## CLI (Optional)

A minimal CLI is included for convenience:

```bash
nearby              # Show help
nearby analyze .    # Build/reindex the current project
nearby status       # Show knowledge base path
```

## How It Works

```
Your Project          Code Nearby               MCP Client
───────────          ────────────              ──────────
src/                  ~/.nearby/                Claude Code
├── auth.py  ──▶      └── your-project/          VS Code
├── api.py   ──▶          ├── _GRAPH.json        Cursor
└── db.py    ──▶          └── .rag/
                              └── index.sqlite3
                            ▲
                    watchdog │ (auto-update)
```

1. `nearby analyze .` — AST parsing (tree-sitter) → chunks → SQLite FTS5 index + dependency graph
2. File watcher keeps the index in sync automatically
3. MCP tools query the index with BM25 + trigram hybrid search, RRF fusion, and graph-aware ranking

## Supported Languages

Python, JavaScript, TypeScript, Go, Rust, Java (via tree-sitter grammars).

## License

MIT
