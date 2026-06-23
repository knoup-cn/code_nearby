# Code Nearby

**Give your LLM the context it needs — right next to your code.**

Code Nearby is an MCP server that indexes your codebase and exposes it to AI assistants as searchable tools. Claude Code (or any MCP client) can search symbols, explore dependencies, and understand your project — without you copy-pasting a single file.

## Why Code Nearby?

LLMs are powerful but blind to your codebase. You end up explaining architecture, pasting files, and repeating yourself. Code Nearby solves this by running as a sidecar MCP server that:

- **Auto-indexes** your project on first connection (AST parsing → SQLite FTS5 + dependency graph)
- **Watches for changes** via watchdog — zero manual re-indexing
- **Exposes 5 MCP tools** for search, exploration, and context retrieval

## Quick Start

### 1. 一键安装

```bash
git clone https://github.com/knoup-cn/code_nearby.git && cd code_nearby && bash setup.sh
```

**零前置依赖** — 脚本自动安装 uv → 拉取 Python 3.12 → 同步依赖 → 输出 MCP 客户端配置。只需 bash + 网络即可。

> 手动安装见下方。

### 2. 配置 MCP 客户端

将 `setup.sh` 输出的 JSON 配置块粘贴进去：

| 客户端 | 配置文件 |
|--------|----------|
| Claude Code | `~/.claude/settings.json` 或 `<project>/.claude/settings.json` |
| VS Code / Cursor | `.vscode/mcp.json` |

配置好后重启客户端即可。首次工具调用会自动构建索引，watchdog 保持实时同步。

> **Tip**: 想预建索引避免首次延迟？运行 `uv run python -c "import code_nearby; code_nearby.analyze('.')"`。

### 3. 开始使用

---

### 手动安装

```bash
pip install code-nearby[mcp]
# 或
uv add code-nearby --extra mcp
```

MCP 配置中 `args` 指向你的安装路径即可。

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
