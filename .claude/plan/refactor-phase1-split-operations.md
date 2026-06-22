# 重构执行计划：优化版（无向后兼容层）

## 📋 执行概览

**任务**：重构 analyze 功能，移除向后兼容层  
**策略**：一次性替换，彻底重构  
**分支**：`refactor/analyze-no-compat`  
**工作目录**：`/home/ubuntu/code/knoup/brain`  
**预计工期**：11 天（比原方案快 45%）

---

## 🎯 第一阶段：方案 3 - 拆分 operations.py（0.5 天）

### 任务目标

将 `operations.py`（613 行）拆分为 4 个职责单一的模块：

```
src/brain/operations/
├── __init__.py     # 空文件（仅文档）
├── config.py       # 配置管理（5 个函数）
├── analysis.py     # 分析逻辑（2 个函数）
├── sync.py         # Git 同步（1 个函数）
└── indexing.py     # 索引生成（3 个函数）
```

### 函数分配

#### config.py（配置管理）
- `needs_overwrite(path: Path) -> bool`
- `init_config(git_repo, kb_path, overwrite) -> tuple[bool, str]`
- `get_status() -> dict | None`
- `clear_config() -> bool`
- `is_git_repo(path: Path) -> bool`

#### analysis.py（分析逻辑）
- `analyze_project(project_path, full_rebuild, auto_sync) -> dict`
- `index_project(project_path, full_rebuild) -> dict`
- `_ensure_rag_gitignore(kb_path: Path) -> None` （内部函数）

#### sync.py（Git 同步）
- `sync_knowledge_base(kb_path, project_path, changes_summary) -> dict`

#### indexing.py（索引生成）
- `_generate_project_index(kb_path, project_path) -> None`
- `_generate_project_graph(kb_path, project_path) -> None`
- `_parse_simple_yaml(yaml_text) -> dict[str, Any]` （内部函数）

### 关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/brain/operations.py` | 删除 | 拆分后删除原文件 |
| `src/brain/operations/__init__.py` | 创建 | 空文件（仅文档） |
| `src/brain/operations/config.py` | 创建 | 配置管理 |
| `src/brain/operations/analysis.py` | 创建 | 分析逻辑 |
| `src/brain/operations/sync.py` | 创建 | Git 同步 |
| `src/brain/operations/indexing.py` | 创建 | 索引生成 |
| `src/brain/__main__.py` | 修改 | 更新导入路径 |
| `src/brain/tui.py` | 修改 | 更新导入路径 |
| `tests/test_sync.py` | 修改 | 更新导入路径 |

### 更新调用点

需要更新的导入路径：

```python
# ❌ 旧导入（将失效）
from brain import operations
operations.analyze_project(...)

# ✅ 新导入（唯一正确方式）
from brain.operations.config import init_config, get_status
from brain.operations.analysis import analyze_project, index_project
from brain.operations.sync import sync_knowledge_base
```

### 验收标准

- [ ] `operations.py` 已删除
- [ ] 4 个子模块已创建
- [ ] `__init__.py` 仅包含文档
- [ ] 所有调用点已更新为直接导入
- [ ] 运行 `pytest tests/ -v` 全部通过
- [ ] 运行 `python -m brain analyze ./` 正常工作

---

## 📦 实施细节

### Step 1：创建目录结构

```bash
mkdir -p src/brain/operations
touch src/brain/operations/__init__.py
```

### Step 2：拆分函数到各模块

1. 创建 `config.py` 并移入配置相关函数
2. 创建 `analysis.py` 并移入分析相关函数
3. 创建 `sync.py` 并移入同步相关函数
4. 创建 `indexing.py` 并移入索引相关函数

### Step 3：更新 `__init__.py`

```python
'''Operations 模块（已拆分为子模块）。

使用方式：
    from brain.operations.config import init_config
    from brain.operations.analysis import analyze_project
    from brain.operations.sync import sync_knowledge_base
'''
```

### Step 4：更新调用点

使用以下命令查找所有调用：

```bash
git grep "from brain import operations"
git grep "from brain.operations import"
git grep "operations\."
```

更新文件：
- `src/brain/__main__.py`
- `src/brain/tui.py`
- `tests/test_sync.py`

### Step 5：删除原文件

```bash
git rm src/brain/operations.py
```

### Step 6：运行测试

```bash
pytest tests/ -v
python -m brain analyze ./test_project --dry-run
```

---

## 🔄 后续阶段预览

### 第二阶段（Week 2）
- 方案 1：拆分 Markdown 生成器（1.5 天）
- 方案 5：统一签名提取（1 天）

### 第三阶段（Week 3）
- 方案 2：统一符号提取（4 天）

### 第四阶段（Week 4，可选）
- 方案 4：流水线重构（4 天）

---

## ⚠️ 注意事项

1. **无兼容层**：不保留 `operations.py`，不在 `__init__.py` 重导出
2. **一次性替换**：所有调用点必须同时更新
3. **测试先行**：确保所有测试通过后再提交
4. **文档同步**：更新 AGENTS.md 和相关文档

---

生成时间：2026-06-22  
会话ID：N/A（第一阶段无需外部模型）  
状态：待执行
