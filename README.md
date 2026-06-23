# Code Nearby

**Give your LLM the context it needs — right next to your code.**

Code Nearby is an MCP server that indexes your codebase and exposes it to AI assistants as searchable tools. Claude Code (or any MCP client) can search symbols, explore dependencies, and understand your project — without you copy-pasting a single file.

## Why Code Nearby?

LLMs are powerful but blind to your codebase. You end up explaining architecture, pasting files, and repeating yourself. Code Nearby solves this by running as a sidecar MCP server that:

- **Auto-indexes** your project on first connection (AST parsing → SQLite FTS5 + dependency graph)
- **Watches for changes** via watchdog — zero manual re-indexing
- **Exposes 5 MCP tools** for search, exploration, and context retrieval

## Quick Start

### 1. Install

```bash
pip install code-nearby[mcp]
# or
uv add code-nearby --extra mcp
```

### 2. Configure your MCP client

Add to `.claude/settings.json` (project or global):

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

That's it. The first tool call will auto-build the index; watchdog keeps it in sync from there.

> **Tip**: Want to pre-build the index to avoid first-call latency? Run `python -c "import code_nearby; code_nearby.analyze('.')"` once.

### 3. Start chatting

Your LLM can now use:

| Tool | What it does |
|------|-------------|
| `nearby_search` | BM25 + trigram hybrid search with language/path filters |
| `nearby_file_info` | List all symbols (functions, classes) in a file |
| `nearby_project_symbols` | Project-wide symbol summary, grouped by file |
| `nearby_module_context` | What a module imports and what depends on it |
| `nearby_status` | Index health: chunk count, files tracked, KB path |

## How It Works

```
Your Project           Code Nearby              MCP Client
───────────           ────────────             ──────────
src/                   ~/.nearby/               Claude Code
├── auth.py  ──▶       └── your-project/         VS Code
├── api.py   ──▶           ├── _GRAPH.json       Cursor
└── db.py    ──▶           └── .rag/
                               └── index.sqlite3
                             ▲
                     watchdog │ (auto-update)
```

1. MCP server starts → watchdog scans project → AST parsing (tree-sitter) → chunks → SQLite FTS5 + dependency graph
2. File watcher incrementally updates the index as you edit
3. BM25 + trigram hybrid retrieval with RRF fusion and graph-aware ranking

## Supported Languages

Python, JavaScript, TypeScript, Go, Rust, Java (via tree-sitter grammars).

## Programmatic API

If you need to use Code Nearby as a library:

```python
import code_nearby

# Build index
code_nearby.analyze("/path/to/project")

# Search
results = code_nearby.search("verify token", max_results=5)
```

## License

MIT
