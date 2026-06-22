"""优化后的重构方案：移除向后兼容层

原方案中存在大量向后兼容代码，增加了实施复杂度。
本文档重新设计重构策略：直接替换，无过渡期。
"""

# ============================================================
# 问题分析：向后兼容的成本
# ============================================================

BACKWARD_COMPATIBILITY_ISSUES = """
# 原方案中的向后兼容问题

## 问题 1：双重维护负担

原方案保留了旧函数作为兼容层：

```python
# 01_split_markdown_generator.py:343
def _generate_obsidian_md_legacy(...) -> str:
    '''旧版函数，委托给新实现（保持向后兼容）。'''
    return generate_obsidian_md(...)

# 05_unify_signature_extraction.py:151
def _extract_signature_legacy_analyzer(...):
    '''旧版 analyzer._extract_signature 兼容适配器。'''
    return _extract_signature_legacy_analyzer(lines, start_line, end_line)
```

**成本**：
- 需要维护两套 API
- 测试覆盖率翻倍
- 代码库膨胀
- 容易出现旧 API 调用残留

## 问题 2：渐进式迁移的幻觉

原方案建议"渐进式替换"：

```
阶段 1：新增新函数，旧函数调用新函数
阶段 2：测试通过后，删除旧函数，重命名新函数
```

**现实**：
- 阶段 1 和阶段 2 之间往往会拖很久
- "临时"的兼容层变成永久负担
- 其他开发者不知道该用哪个 API
- 代码审查时容易混淆

## 问题 3：不必要的复杂度

原方案在 operations/__init__.py 中重导出：

```python
# 配置管理
from brain.operations.config import (
    clear_config,
    get_status,
    init_config,
    ...
)
```

**成本**：
- 增加一层间接调用
- IDE 跳转变复杂
- 导入路径歧义（应该用哪个？）
"""

# ============================================================
# 优化策略：直接替换，无过渡期
# ============================================================

OPTIMIZED_STRATEGY = """
# 优化策略：直接替换

## 核心原则

1. **一次性替换**：不保留旧函数
2. **统一导入路径**：只有一种正确的导入方式
3. **强制迁移**：重构后旧代码无法运行，必须适配
4. **测试先行**：确保新实现正确后再删除旧代码

## 实施步骤

### 步骤 1：在分支中完成重构

```bash
git checkout -b refactor/analyze-optimization
# 完成所有重构
# 运行全部测试
```

### 步骤 2：一次性替换（无兼容层）

```python
# ❌ 旧方案（有兼容层）
def _generate_obsidian_md_legacy(...):
    return generate_obsidian_md(...)

# ✅ 新方案（直接替换）
# 删除旧函数，新函数直接使用旧名称
def _generate_obsidian_md(...) -> str:
    '''生成 Obsidian Markdown（重构版）。'''
    sections = [
        _generate_frontmatter(data),
        _generate_header(data),
        ...
    ]
    return "\\n\\n".join(s for s in sections if s)
```

### 步骤 3：更新所有调用点

使用 IDE 的"查找所有引用"功能：

```bash
# 查找旧 API 调用
git grep "_generate_obsidian_md"
git grep "_extract_symbols"

# 逐一更新调用点（IDE 重构工具）
```

### 步骤 4：测试验证

```bash
# 运行全部测试
pytest tests/ -v

# 手动测试关键路径
python -m brain analyze ./test_project
python -m brain index ./test_project
```

### 步骤 5：合并到主分支

```bash
git add .
git commit -m "refactor(analyze): optimize without backward compatibility"
git push origin refactor/analyze-optimization

# 创建 PR，代码审查
# 合并后，旧 API 立即失效
```

## 优势

1. **代码更简洁**：无冗余兼容层
2. **维护成本低**：只有一套 API
3. **避免歧义**：只有一种正确的调用方式
4. **强制升级**：确保所有代码都使用新实现
"""

# ============================================================
# 优化后的方案 1：拆分 Markdown 生成器
# ============================================================

OPTIMIZED_PLAN_1 = """
# 优化后的方案 1：拆分 Markdown 生成器

## 原方案问题

保留了 `_generate_obsidian_md_legacy` 兼容函数。

## 优化后方案

直接替换，无兼容层：

```python
# src/brain/markdown_renderer.py（新文件）

def generate_obsidian_md(...) -> str:
    '''生成 Obsidian Markdown。'''
    sections = [
        _generate_frontmatter(metadata, symbols, dependencies),
        _generate_header(module_name, metadata),
        _generate_public_api(symbols["functions"], relative_path),
        _generate_classes(symbols["classes"], relative_path),
        _generate_dependencies(dependencies, project_name),
        _generate_footer(),
    ]
    return "\\n\\n".join(s for s in sections if s)
```

```python
# src/brain/analyzer.py

from brain.markdown_renderer import generate_obsidian_md

def analyze_file(file_path: Path, kb_path: Path, project_root: Path) -> None:
    # ... 提取结构 ...
    
    # 直接调用新实现
    content = generate_obsidian_md(
        file_path=file_path,
        relative_path=relative,
        metadata=metadata,
        symbols=symbols,
        dependencies=dependencies,
        project_name=project_name,
    )
    
    # ... 写入文件 ...
```

## 迁移步骤

1. 创建 `src/brain/markdown_renderer.py`
2. 实现所有子函数
3. 在 `analyzer.py` 中删除旧 `_generate_obsidian_md`
4. 导入并使用 `generate_obsidian_md`
5. 运行测试验证

**无需**：
- ❌ 保留 `_generate_obsidian_md_legacy`
- ❌ 委托调用
- ❌ 渐进式替换
"""

# ============================================================
# 优化后的方案 2：统一符号提取
# ============================================================

OPTIMIZED_PLAN_2 = """
# 优化后的方案 2：统一符号提取

## 原方案问题

建议"旧实现委托给新实现"，保留 `_extract_symbols` 旧函数。

## 优化后方案

直接在 `tree_sitter_utils.py` 实现通用遍历器，删除 analyzer 和 chunker 中的旧实现：

```python
# src/brain/tree_sitter_utils.py

def walk_symbols(
    root: Node,
    src: bytes,
    source: str,
    cfg: LanguageConfig,
    visitor: SymbolVisitor,
) -> None:
    '''遍历顶层符号并回调 visitor。'''
    _walk_scope(
        scope_node=root,
        src=src,
        source=source,
        cfg=cfg,
        visitor=visitor,
        scope=[],
        parent_class=None,
    )
```

```python
# src/brain/analyzer.py

from brain.tree_sitter_utils import walk_symbols, AnalyzerVisitor

def analyze_file(file_path, kb_path, project_root):
    # ... 解析 AST ...
    
    # 直接使用新实现
    visitor = AnalyzerVisitor()
    walk_symbols(root, src, source, cfg, visitor)
    symbols = visitor.get_symbols()
    
    # ... 生成文档 ...
```

```python
# src/brain/rag/chunker.py

from brain.tree_sitter_utils import walk_symbols, ChunkerVisitor

def chunk_file(file_path, project_root):
    # ... 解析 AST ...
    
    # 直接使用新实现
    visitor = ChunkerVisitor(builder)
    walk_symbols(root, src, source, cfg, visitor)
    
    return builder.chunks
```

## 迁移步骤

1. 在 `tree_sitter_utils.py` 实现 `walk_symbols` + visitor 协议
2. **删除** `analyzer._extract_symbols`
3. **删除** `chunker._walk_scope`
4. 更新 `analyzer.py` 和 `chunker.py` 调用
5. 运行测试验证

**无需**：
- ❌ 保留旧 `_extract_symbols` 函数
- ❌ "渐进式替换"
- ❌ 等效性测试（直接替换）
"""

# ============================================================
# 优化后的方案 3：拆分 operations.py
# ============================================================

OPTIMIZED_PLAN_3 = """
# 优化后的方案 3：拆分 operations.py

## 原方案问题

在 `operations/__init__.py` 中重导出所有 API，增加间接层。

## 优化后方案

直接拆分，不保留 `operations.py`，也不在 `__init__.py` 重导出：

```
src/brain/
├── operations/
│   ├── __init__.py          # 空文件（或仅文档）
│   ├── config.py            # 配置管理
│   ├── analysis.py          # 分析逻辑
│   ├── sync.py              # Git 同步
│   └── indexing.py          # 索引生成
```

```python
# src/brain/operations/__init__.py（空文件）
'''Operations 模块（已拆分）。

请直接导入子模块：
- from brain.operations.config import init_config
- from brain.operations.analysis import analyze_project
- from brain.operations.sync import sync_knowledge_base
'''
```

## 更新调用点

```python
# ❌ 旧调用（已失效）
from brain import operations
operations.analyze_project(...)

# ✅ 新调用（唯一正确方式）
from brain.operations.analysis import analyze_project
analyze_project(...)
```

```python
# src/brain/__main__.py（CLI 入口）

from brain.operations.config import init_config, get_status
from brain.operations.analysis import analyze_project, index_project
from brain.operations.sync import sync_knowledge_base

# 直接使用
```

## 迁移步骤

1. 创建 `operations/` 目录和 4 个文件
2. 将函数移到对应文件
3. **删除** `operations.py`
4. `__init__.py` 保持空（不重导出）
5. 更新所有调用点（直接导入子模块）
6. 运行测试验证

**无需**：
- ❌ 在 `__init__.py` 重导出
- ❌ 保留 `operations.py`
- ❌ 兼容旧导入路径
"""

# ============================================================
# 优化后的方案 4：流水线重构
# ============================================================

OPTIMIZED_PLAN_4 = """
# 优化后的方案 4：流水线重构

## 原方案问题

保留旧 `analyze_file` 函数作为兼容层。

## 优化后方案

直接替换为流水线实现：

```python
# src/brain/analyzer.py

from brain.analysis_pipeline import AnalysisPipeline

# 全局流水线实例（单例）
_pipeline = AnalysisPipeline()

def analyze_file(file_path: Path, kb_path: Path, project_root: Path) -> None:
    '''分析单个文件并写入知识库。'''
    _pipeline.analyze_file(file_path, kb_path, project_root)
```

## 迁移步骤

1. 创建 `src/brain/analysis_pipeline.py`
2. 实现所有协议和组件
3. 在 `analyzer.py` 中直接替换 `analyze_file` 实现
4. 运行测试验证

**无需**：
- ❌ 保留旧 `analyze_file` 实现
- ❌ 委托调用
- ❌ "渐进式替换"
"""

# ============================================================
# 优化后的方案 5：统一签名提取
# ============================================================

OPTIMIZED_PLAN_5 = """
# 优化后的方案 5：统一签名提取

## 原方案问题

保留 `_extract_signature_legacy_analyzer` 和 `_signature_legacy_chunker` 适配器。

## 优化后方案

直接在 `tree_sitter_utils.py` 实现统一函数，删除旧实现：

```python
# src/brain/tree_sitter_utils.py

def extract_signature(
    source_lines: list[str],
    span_node: Node,
    inner_node: Node,
    format: str = "compact"
) -> str:
    '''提取函数/类签名。
    
    Args:
        format: "compact"（压缩空白）或 "multiline"（保留格式）
    '''
    if format == "compact":
        return _extract_signature_compact(source_lines, span_node, inner_node)
    else:
        return _extract_signature_multiline(source_lines, span_node, inner_node)
```

```python
# src/brain/analyzer.py

from brain.tree_sitter_utils import extract_signature

# 直接使用
signature = extract_signature(lines, span_node, inner, format="multiline")
```

```python
# src/brain/rag/chunker.py

from brain.tree_sitter_utils import extract_signature

# 直接使用
signature = extract_signature(
    source_text.split("\\n"), 
    span_node, 
    inner, 
    format="compact"
)
```

## 迁移步骤

1. 在 `tree_sitter_utils.py` 实现 `extract_signature`
2. **删除** `analyzer._extract_signature`
3. **删除** `chunker._signature`
4. 更新 analyzer 和 chunker 调用
5. 运行测试验证

**无需**：
- ❌ 适配器函数
- ❌ "兼容旧接口"
- ❌ 渐进式替换
"""

# ============================================================
# 总结：优化收益
# ============================================================

OPTIMIZATION_BENEFITS = """
# 优化后的收益对比

## 代码行数对比

| 方案 | 原方案 | 优化后 | 减少 |
|------|--------|--------|------|
| 方案 1 | 360 行 | 250 行 | -30% |
| 方案 2 | 530 行 | 380 行 | -28% |
| 方案 3 | 850 行 | 620 行 | -27% |
| 方案 4 | 450 行 | 320 行 | -29% |
| 方案 5 | 430 行 | 280 行 | -35% |
| **总计** | **2620 行** | **1850 行** | **-29%** |

## 实施时间对比

| 方案 | 原方案 | 优化后 | 减少 |
|------|--------|--------|------|
| 方案 1 | 2-3 天 | 1.5 天 | -40% |
| 方案 2 | 5-7 天 | 4 天 | -40% |
| 方案 3 | 1 天 | 0.5 天 | -50% |
| 方案 4 | 5-7 天 | 4 天 | -40% |
| 方案 5 | 2 天 | 1 天 | -50% |
| **总计** | **15-20 天** | **11 天** | **-45%** |

## 维护成本对比

| 指标 | 原方案 | 优化后 | 改善 |
|------|--------|--------|------|
| API 数量 | 2 套（新+旧） | 1 套 | -50% |
| 测试覆盖 | 双倍 | 正常 | -50% |
| 导入路径 | 多种方式 | 唯一方式 | -70% |
| 代码复杂度 | 高（委托层） | 低（直接） | -40% |

## 清晰度对比

**原方案（有兼容层）**：
```python
# 开发者困惑：用哪个？
from brain.operations import analyze_project  # 方式 1
from brain.operations.analysis import analyze_project  # 方式 2

# 哪个是新的？
_generate_obsidian_md()  # 旧的？
generate_obsidian_md()   # 新的？
_generate_obsidian_md_legacy()  # 这是啥？
```

**优化后（无兼容层）**：
```python
# 唯一正确的方式
from brain.operations.analysis import analyze_project

# 只有一个函数
generate_obsidian_md()  # 唯一实现
```

## 风险对比

| 风险 | 原方案 | 优化后 |
|------|--------|--------|
| API 混用 | 高 | 无（只有一个） |
| 遗留代码 | 高（兼容层残留） | 无 |
| 维护分裂 | 高（新旧并存） | 无 |
| 测试不完整 | 中（容易忘记旧 API） | 低 |
"""

# ============================================================
# 实施建议
# ============================================================

IMPLEMENTATION_GUIDE = """
# 优化后的实施建议

## 核心原则

**一次性替换，彻底重构**

- ✅ 在分支中完成所有重构
- ✅ 确保测试全部通过
- ✅ 一次性合并，旧代码立即失效
- ❌ 不保留兼容层
- ❌ 不做渐进式替换
- ❌ 不重导出 API

## 实施步骤

### 第一阶段（第 1 周）

**Day 1-2：方案 3（拆分 operations.py）**
- 创建 4 个子模块
- 删除 `operations.py`
- 更新所有调用点
- 测试验证

**Day 3：方案 6（评估 signature_hash）**
- 调研使用情况
- 移除或文档化

**第一阶段验收**：
- [ ] `operations.py` 已删除
- [ ] 所有调用更新为直接导入
- [ ] 测试全部通过

---

### 第二阶段（第 2-3 周）

**Week 2：方案 1 + 方案 5**
- Day 1-2：拆分 Markdown 生成器
- Day 3：统一签名提取
- Day 4-5：测试和优化

**Week 3：方案 2（统一符号提取）**
- Day 1-2：实现 visitor 模式
- Day 3-4：删除旧实现，更新调用
- Day 5：测试验证

**第二阶段验收**：
- [ ] 代码重复度 < 5%
- [ ] 所有旧函数已删除
- [ ] 测试覆盖率 > 80%

---

### 第三阶段（第 4-5 周，可选）

**Week 4：方案 4（流水线重构）**
- 实现流水线组件
- 直接替换 `analyze_file`
- 测试验证

**Week 5：方案 7 + 8（架构优化，可选）**
- 仅在有明确需求时实施
- 否则暂停，等待实际需求

---

## 验收标准

### 必须满足

- [ ] 所有旧函数已删除（无兼容层）
- [ ] 只有一种正确的导入方式
- [ ] 测试覆盖率 > 80%
- [ ] 性能无显著下降（< 5%）
- [ ] 所有测试通过

### 禁止存在

- [ ] ❌ 任何 `*_legacy` 函数
- [ ] ❌ 任何委托调用
- [ ] ❌ 多种导入路径
- [ ] ❌ 旧 `operations.py` 文件
- [ ] ❌ 重导出层（`__init__.py`）

---

## 回滚计划

如果重构后出现问题：

```bash
# 立即回滚整个分支
git revert <merge-commit-hash>
git push origin main
```

**不需要**：
- ❌ 保留旧代码"以防万一"
- ❌ Feature flag 切换
- ❌ 渐进式回滚

**原因**：
- 所有重构在分支中完成
- 合并前已充分测试
- 要么全部成功，要么全部回滚
- 没有中间状态
"""

if __name__ == "__main__":
    print("=" * 60)
    print("优化后的重构方案：移除向后兼容层")
    print("=" * 60)
    print()
    print(BACKWARD_COMPATIBILITY_ISSUES)
    print()
    print(OPTIMIZED_STRATEGY)
    print()
    print(OPTIMIZATION_BENEFITS)
    print()
    print(IMPLEMENTATION_GUIDE)
