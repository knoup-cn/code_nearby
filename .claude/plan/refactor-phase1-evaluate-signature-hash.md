# 方案 6 执行结果：signature_hash 评估

## 📋 调研结果

### signature_hash 使用情况

#### 写入位置（5 处）
1. `analyzer.py:148` - 计算函数 signature_hash
2. `analyzer.py:187` - 计算方法 signature_hash  
3. `analyzer.py:207` - 计算类 signature_hash
4. `analyzer.py:426` - 写入 Markdown frontmatter
5. `graph.py:90` - 从 frontmatter 读取并复制到图结构

#### 读取位置（1 处）
- `graph.py:90` - 仅读取并复制，**无实际使用**

#### 测试位置（3 处）
- `test_analyzer.py` - 仅验证格式（8 位十六进制）
- `test_graph.py` - 仅验证存在性

### 结论

✅ **signature_hash 是 YAGNI（You Aren't Gonna Need It）**

**原因**：
1. **只写不读**：只在生成时计算并存储，从未被读取用于实际逻辑
2. **无增量逻辑**：没有代码根据 signature_hash 判断是否需要重新分析
3. **功能重复**：已有 `last_commit` 机制实现增量更新
4. **维护成本**：每个符号都计算哈希，增加计算开销

---

## 🎯 优化方案

### 选项 A：直接移除（推荐）

**操作**：
1. 删除 `_compute_signature_hash` 函数
2. 从符号字典中移除 `signature_hash` 字段
3. 从 Markdown frontmatter 移除
4. 从 graph.py 移除
5. 更新测试

**收益**：
- 减少 50+ 行代码
- 每个符号节省 1 次 SHA256 计算
- 简化数据结构

**风险**：
- 低（无实际使用者）

### 选项 B：保留并文档化

如果您认为未来可能需要：

```python
def _compute_signature_hash(signature: str) -> str:
    """计算签名哈希（预留用于未来增量更新）。
    
    用途：
    - 检测函数签名变更（参数、返回类型变化）
    - 触发重新索引
    
    注意：当前未被使用，保留供未来扩展。
    """
    normalized = signature.strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:8]
```

---

## 📊 决策建议

**推荐：选项 A（移除）**

理由：
1. 项目已有完善的增量更新机制（基于 git commit）
2. 5 个月未被使用，说明当前需求不需要
3. YAGNI 原则：不要为未来可能的需求增加复杂度
4. 如果未来真的需要，可以随时添加回来

---

## 实施计划

如果选择移除，我将：
1. 从 analyzer.py 移除计算和字段
2. 从 graph.py 移除读取
3. 更新测试（移除 signature_hash 断言）
4. 运行全部测试验证
5. 提交变更

预计时间：30 分钟

---

**您的决定**：移除 signature_hash 还是保留并文档化？
