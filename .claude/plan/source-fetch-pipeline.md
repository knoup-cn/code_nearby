# 📋 实施计划：Source Fetch 管线重构

> **目标**：将 brain 检索管线从「索引内嵌源码」重构为 `Code → AST → Symbol Index → Code Graph → Candidate Selection → Source Fetch → Context Assembly → LLM`
>
> **状态**：待审查
> **日期**：2026-06-23

---

## 一、背景与动机

### 当前管线问题

```
Code → AST chunk → SQLite(content + FTS blob + trigram) → search() 返回完整 content → assemble
                         ↑
                   content 存了两份：chunks 表 + chunks_fts 影子表
                   索引与磁盘可能漂移
                   context 被 chunk 边界限定，无法扩展
```

### 目标管线

```
Code → AST → Symbol Index → Code Graph → Candidate Selection → Source Fetch → Context Assembly → LLM
  ↑                 ↑              ↑              ↑                   ↑                   ↑
tree-sitter    FTS5 元数据    _GRAPH.json    BM25+trigram     从磁盘读源码         token 预算
切分不变       不含 content   依赖图不变      +RRF 不变        支持窗口扩展         组装不变
```

### 核心原则

1. **Index 是地图，不是仓库**——只存元数据 + 检索 token，不存完整源码
2. **磁盘是唯一真相源**——Source Fetch 读到的一定是最新版本
3. **窗口扩展天然成立**——读到文件后可自由扩展上下文（C11 从进阶降为内置）
4. **增量索引不变**——content_hash 仍用于变更检测，chunker 仍产出完整 Chunk

---

## 二、技术方案：方案 A（推荐）

### 方案概述

**仅从 `chunks` 表移除 `content` 列。** FTS blob 在 upsert 时计算并存入 FTS5 影子表（`chunks_fts`），content 不落地到 chunks 主表。检索返回时 Source Fetch 从磁盘读取。

### 为什么是方案 A 而非其他

| 维度 | 方案 A：移除 content 列 | 方案 B：保留 content 但不返回 | 方案 C：content 替换为 fts_blob 文本 |
|------|--------------------------|------------------------------|--------------------------------------|
| DB 体积 | **最小**（省掉 content 副本） | 不变（仍存 content） | 中等（fts_blob 比 content 略大，含 token 扩展） |
| 实现复杂度 | 中等（改 schema + 改所有 content 读取点） | **最低**（仅改 assemble） | 较高（需在 chunker 侧预计算 blob，新增列） |
| 磁盘漂移 | **彻底解决**（返回时从磁盘读最新） | 未解决（返回的仍是索引时的 content） | 未解决 |
| 窗口扩展 | **天然支持** | 需额外实现 | 需额外实现 |
| 向后兼容 | 需重建索引 | 兼容 | 需重建索引 |
| 代码意图 | **最清晰**——index 不是内容仓库 | 模糊——存了但不返回，浪费空间 | 中间态 |

**选择方案 A**，因为它完整实现了「索引是地图」的架构意图，且 DB 体积最小、窗口扩展天然成立。

---

## 三、实施步骤

### Step 1：新增 `source_fetch.py` 模块

**文件**：`src/brain/rag/source_fetch.py`（**新建**）

**职责**：从磁盘按位置读取源码，支持窗口扩展。

**数据结构**：

```python
@dataclass(frozen=True, slots=True)
class SourceSnippet:
    """从磁盘读取的源码片段。"""
    file_path: str
    start_line: int       # 1-indexed，含窗口扩展
    end_line: int
    content: str          # 实际源码文本
    original_start: int   # 命中 chunk 的原始起始行（不含扩展）
    original_end: int     # 命中 chunk 的原始结束行
```

**核心函数**：

```python
def fetch_source(
    project_root: Path,
    file_path: str,
    start_line: int,
    end_line: int,
    *,
    context_before: int = 0,
    context_after: int = 0,
) -> SourceSnippet | None:
    """从磁盘读取源文件的行范围。
    
    读取失败（文件不存在/权限错误/行号越界）返回 None。
    context_before/after 用于窗口扩展——不会超出文件边界。
    """
    full_path = project_root / file_path
    try:
        lines = full_path.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        return None

    total = len(lines)
    actual_start = max(1, start_line - context_before)
    actual_end = min(total, end_line + context_after)

    snippet = "\n".join(lines[actual_start - 1 : actual_end])
    return SourceSnippet(
        file_path=file_path,
        start_line=actual_start,
        end_line=actual_end,
        content=snippet,
        original_start=start_line,
        original_end=end_line,
    )


def expand_window(
    project_root: Path,
    file_path: str,
    start_line: int,
    end_line: int,
    strategy: str = "moderate",
) -> tuple[int, int]:
    """计算窗口扩展参数。
    
    Strategies:
    - "none": (0, 0)
    - "minimal": (2, 2) — 前后各 2 行
    - "moderate": (5, 5) — 前后各 5 行（默认）
    - "generous": (10, 10)
    """
    ...
```

**测试**：`tests/test_source_fetch.py`（**新建**）

---

### Step 2：修改 `schema.py` — Chunk 语义调整

**文件**：`src/brain/rag/schema.py`

**改动**：

```diff
- content: str  # 符号的源码体
+ content: str  # 符号的源码体（仅用于 chunker→index upsert 期间构建 FTS blob 与 content_hash；
+               #  不持久化到 chunks 表；检索时通过 Source Fetch 从磁盘获取）
```

`schema.py` 自身无需逻辑变更——`Chunk` dataclass 保留 `content` 字段供 chunker 和 index.upsert 内部使用。变更的是下游对 content 的期望：**get_chunks() 返回的 Chunk 其 content 为空字符串**。

---

### Step 3：修改 `index.py` — 移除 content 持久化

**文件**：`src/brain/rag/index.py`

**核心改动**：

**3a. DDL — 移除 content 列**

```python
_DDL = """
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id      TEXT PRIMARY KEY,
  file_path     TEXT NOT NULL,
  language      TEXT NOT NULL,
  chunk_type    TEXT NOT NULL,
  symbol        TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  parent_class  TEXT NOT NULL DEFAULT '',
  start_line    INTEGER NOT NULL,
  end_line      INTEGER NOT NULL,
  imports       TEXT NOT NULL DEFAULT '',
  signature     TEXT NOT NULL DEFAULT '',
  docstring     TEXT NOT NULL DEFAULT '',
  content_hash  TEXT NOT NULL
);
-- chunks_fts 和 chunks_tri 不变
"""
```

**3b. `upsert()` — 不写入 content**

```python
def upsert(self, chunks: Iterable[Chunk]) -> int:
    count = 0
    with self._conn:
        for chunk in chunks:
            self._delete_fts(chunk.chunk_id)
            row = chunk.to_row()
            del row["content"]  # ← 不写入 chunks 表
            self._conn.execute(
                "INSERT OR REPLACE INTO chunks (...) VALUES (...)", row
            )
            # FTS blob 仍正常构建（使用 chunk.content）
            self._conn.execute(
                "INSERT INTO chunks_fts(chunk_id, blob) VALUES (?, ?)",
                (chunk.chunk_id, _search_blob(chunk)),
            )
            # trigram 不变
            self._conn.execute(
                "INSERT INTO chunks_tri(chunk_id, sym) VALUES (?, ?)",
                (chunk.chunk_id, f"{chunk.symbol} {chunk.qualified_name}"),
            )
            count += 1
    return count
```

**3c. `_COLUMNS` 常量 — 移除 content**

```python
_COLUMNS = (
    "chunk_id, file_path, language, chunk_type, symbol, qualified_name, "
    "parent_class, start_line, end_line, imports, signature, docstring, "
    "content_hash"
)
```

**3d. `get_chunks()` 返回的 Chunk 中 content=""——需要 from_row 兼容**

`Chunk.from_row()` 已经对缺失字段容错（`row.get("content", "")`），但需要显式处理：修改 `from_row` 设置 `content=""` 的默认值，调用方不应再依赖 content 字段。

**3e. 旧 Schema 迁移**

```python
def _migrate_if_needed(self) -> bool:
    """检测旧 schema（有 content 列）→ 返回 True 表示需要全量重建。"""
    cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(chunks)")}
    return "content" in cols
```

在 `RagIndex.open()` 中调用，若检测到旧 schema 则抛出明确错误提示用户执行 `brain analyze --full`。

---

### Step 4：修改 `graph.py` — 不再依赖 content 列

**文件**：`src/brain/graph.py`

**改动**：`lines_of_code` 计算方式

```diff
- module_rows = conn.execute(
-     "SELECT file_path, language, imports, content FROM chunks WHERE chunk_type = 'module'"
- ).fetchall()
+ module_rows = conn.execute(
+     "SELECT file_path, language, imports, start_line, end_line FROM chunks WHERE chunk_type = 'module'"
+ ).fetchall()

  for row in module_rows:
      ...
-     "lines_of_code": row["content"].count("\n") + 1,
+     "lines_of_code": row["end_line"] - row["start_line"] + 1,
```

---

### Step 5：修改 `retrieve.py` — 检索结果不再带 content

**文件**：`src/brain/rag/retrieve.py`

**5a. `rerank_heuristic()` — 移除 content 依赖**

当前 `rerank_heuristic` 有两处用到 `chunk.content`：

```python
# Line 135: 内容小写匹配
content_lower = sc.chunk.content.lower()

# Line 148: 多词命中计数
hits = sum(1 for t in query_terms if t in content_lower or t in sig_lower)
```

**处理**：将 content 匹配降级为仅依赖 signature + docstring + qualified_name：

```python
# 3. 多词命中密度（基于可用的文本字段）
text_lower = " ".join([
    sc.chunk.signature.lower(),
    sc.chunk.docstring.lower() if sc.chunk.docstring else "",
]).lower()
hits = sum(1 for t in query_terms if t in text_lower or t in sig_lower)
```

影响评估：content-based 命中加分仅 0.01×(hits-1)，是启发式中最弱的信号。BM25 召回已经覆盖了 content 相关性。移除后对排序质量影响极小。

**5b. `search()` 函数签名不变**，返回的 `ScoredChunk` 中 chunk.content 为空字符串。

---

### Step 6：修改 `assemble.py` — 接入 Source Fetch

**文件**：`src/brain/rag/assemble.py`

**核心改动**：`assemble()` 新增 `project_root` 参数，调用 `source_fetch` 获取源码。

```python
def assemble(
    query: str,
    results: list[ScoredChunk],
    budget: int | None = None,
    *,
    project_root: Path | None = None,       # 新增
    window_strategy: str = "moderate",       # 新增
) -> dict[str, Any]:
```

每个 chunk 在纳入前：

```python
for scored in results:
    chunk = scored.chunk
    
    # Source Fetch
    if project_root:
        before, after = expand_window_params(window_strategy)
        snippet = fetch_source(
            project_root, chunk.file_path,
            chunk.start_line, chunk.end_line,
            context_before=before, context_after=after,
        )
        if snippet is None:
            # 文件不存在 — 跳过此结果
            continue
        content = snippet.content
        actual_lines = f"{snippet.start_line}-{snippet.end_line}"
    else:
        # 无 project_root 时回退到 chunk 自身（兼容测试场景）
        content = chunk.content
        actual_lines = f"{chunk.start_line}-{chunk.end_line}"
    
    cost = estimate_tokens(content) + estimate_tokens(meta)
    ...
```

**窗口扩展策略映射**：

```python
WINDOW_PRESETS = {
    "none": (0, 0),
    "minimal": (2, 2),
    "moderate": (5, 5),
    "generous": (10, 10),
}
```

**`_entry()` 输出调整**：

```diff
  return {
      ...
-     "lines": f"{chunk.start_line}-{chunk.end_line}",
-     "ref": f"{chunk.file_path}:{chunk.start_line}",
+     "lines": actual_lines,          # 窗口扩展后的行范围
+     "ref": f"{chunk.file_path}:{snippet.original_start}",  # 原始命中行
+     "context_window": window_strategy,
  }
```

---

### Step 7：修改入口层 — 传入 project_root

**文件**：`src/brain/__init__.py`、`src/brain/cli.py`

**改动**：向 `assemble.assemble()` 传入 `project_root`。

```python
# __init__.py
return assemble.assemble(
    query, scored, budget=budget,
    project_root=target,  # 新增
)

# cli.py — 同理
```

---

### Step 8：修改 `analysis.py` — 适配新 index schema

**文件**：`src/brain/operations/analysis.py`

检查是否有直接引用 `chunks.content` 的地方。当前 `run_full_analysis()` 仅通过 `index.upsert()` 写入，不直接读 content——**无需改动**。

但需要处理旧 schema 检测：在 `RagIndex.open()` 时做迁移检测（见 Step 3e），`run_full_analysis` 中若检测到旧 schema 则自动触发 full rebuild。

---

### Step 9：测试更新与新测试

| 测试文件 | 操作 | 说明 |
|----------|------|------|
| `tests/test_source_fetch.py` | **新建** | 测试 fetch_source() 基础读取、窗口扩展、文件不存在、越界处理 |
| `tests/test_rag_index.py` | 修改 | 移除 content 列相关的断言；验证 upsert 不存 content |
| `tests/test_rag_retrieve.py` | 修改 | 适配 chunk.content="" |
| `tests/test_rag_e2e.py` | 修改 | 传入 project_root 参数 |
| `tests/test_rag_chunker.py` | 不变 | chunker 仍产出完整 Chunk |

---

## 四、影响评估

### 性能影响

| 指标 | 变化 | 说明 |
|------|------|------|
| 索引体积 | **↓ 30-50%** | content 是 chunks 表最大列 |
| 检索延迟 | **+ 5-15ms/结果** | 磁盘读取开销（~0.1ms 打开文件 + 读取） |
| 首次检索 | 略快 | 减少了 SQLite 返回 content 的 IO |
| 内存占用 | 不变 | 仍需在 assemble 时持有源码文本 |

### 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 文件被删除后检索命中 | 结果丢失 | `fetch_source()` 返回 None → 跳过该结果，计入 `skipped` 计数 |
| 行号越界（文件变短） | 片段不完整 | 自动 clamp 到文件范围；返回实际行范围 |
| 旧索引不兼容 | 用户报错 | `RagIndex.open()` 检测旧 schema → 提示 `brain analyze --full` |
| 窗口扩展后超出 token 预算 | 截断不完整 | 先在 `estimate_tokens` 后判定，超预算时降级到 "none" 策略 |

---

## 五、关键文件变更清单

| # | 文件 | 操作 | 说明 |
|---|------|------|------|
| 1 | `src/brain/rag/source_fetch.py` | **新建** | Source Fetch 层 |
| 2 | `src/brain/rag/schema.py` | 微调 | content 字段文档注释 |
| 3 | `src/brain/rag/index.py` | 修改 | DDL 移除 content；`upsert()` 不写 content；`_COLUMNS` 更新；旧 schema 迁移检测 |
| 4 | `src/brain/graph.py` | 修改 | `lines_of_code` 改用 `end_line - start_line` |
| 5 | `src/brain/rag/retrieve.py` | 修改 | `rerank_heuristic()` 移除 content 依赖 |
| 6 | `src/brain/rag/assemble.py` | 修改 | 接入 `source_fetch`；新增 `project_root`/`window_strategy` 参数 |
| 7 | `src/brain/__init__.py` | 修改 | `search()` 传入 `project_root` |
| 8 | `src/brain/cli.py` | 修改 | `search` 命令传入 `project_root`；新增 `--window` CLI 选项 |
| 9 | `src/brain/operations/analysis.py` | 微调 | 旧 schema 自动 full rebuild |
| 10 | `tests/test_source_fetch.py` | **新建** | Source Fetch 测试 |
| 11 | `tests/test_rag_index.py` | 修改 | 适配无 content schema |
| 12 | `tests/test_rag_retrieve.py` | 修改 | 适配 content="" |
| 13 | `tests/test_rag_e2e.py` | 修改 | 传入 project_root |

---

## 六、不在本次范围内

- ❌ Embedding / 向量检索（G7/G8/C1/C5 — 仍为进阶）
- ❌ LSP / ctags 符号跳转（C10 — 仍为进阶）
- ❌ Cross-encoder 重排（C9 — 仍为进阶）
- ❌ watchdog 实时增量（G5 — 仍为进阶）
- ❌ Markdown 产物 / Obsidian 目标 1 相关

---

## 七、SESSION_ID

- CODEX_SESSION: N/A（模型不可用，计划由 Claude 综合制定）
- GEMINI_SESSION: N/A（API 额度耗尽）
