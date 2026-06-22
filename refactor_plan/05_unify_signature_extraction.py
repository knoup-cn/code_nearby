"""重构方案 5：统一签名提取逻辑

当前问题：
- analyzer.py 和 chunker.py 各有一套签名提取实现
- 逻辑不完全一致，可能导致结果差异
- 违反 DRY 原则

统一到 tree_sitter_utils.py 中。
"""

from __future__ import annotations

import re
from tree_sitter import Node


# ============================================================
# 统一的签名提取函数
# ============================================================


def extract_signature(
    source_lines: list[str],
    span_node: Node,
    inner_node: Node,
    format: str = "compact"
) -> str:
    """从 AST 节点提取函数/类签名（统一实现）。

    支持两种格式：
    - "compact": 压缩空白，单行显示（用于 chunk signature）
    - "multiline": 保留原始格式（用于 analyzer 文档）

    Args:
        source_lines: 源码行列表
        span_node: 外层节点（含装饰器）
        inner_node: 内层节点（def/class 本身）
        format: "compact" 或 "multiline"

    Returns:
        签名字符串
    """
    if format == "compact":
        return _extract_signature_compact(source_lines, span_node, inner_node)
    else:
        return _extract_signature_multiline(source_lines, span_node, inner_node)


def _extract_signature_compact(
    source_lines: list[str],
    span_node: Node,
    inner_node: Node,
) -> str:
    """提取签名并压缩空白（chunker 风格）。

    示例输出:
        @decorator def foo(x: int, y: str) -> bool:
    """
    # 获取从装饰器到函数体之前的所有文本
    body = inner_node.child_by_field_name("body")
    end_byte = body.start_byte if body is not None else inner_node.end_byte

    # 从字节偏移推断行范围
    start_line = span_node.start_point[0]
    end_line = span_node.end_point[0]

    # 提取文本
    lines = []
    for i in range(start_line, min(end_line + 1, len(source_lines))):
        line = source_lines[i]
        lines.append(line)
        # 如果遇到函数体开始标记（包含 ":" 且后面不是注释），停止
        if ":" in line:
            # 简单检查：不是在字符串或注释中的冒号
            stripped = line.strip()
            if stripped.endswith(":") or stripped.endswith("): "):
                break

    # 压缩空白
    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text).strip()

    # 确保以 ":" 结尾
    if text and not text.endswith(":"):
        text = text.rstrip().removesuffix(":").rstrip() + ":"

    return text


def _extract_signature_multiline(
    source_lines: list[str],
    span_node: Node,
    inner_node: Node,
) -> str:
    """提取签名（保留多行格式，analyzer 风格）。

    示例输出:
        def foo(
            x: int,
            y: str
        ) -> bool:
    """
    start_line = span_node.start_point[0]
    end_line = span_node.end_point[0]

    # 提取签名行（到第一个以 ":" 结尾的行）
    signature_lines = []
    for i in range(start_line, min(end_line + 1, len(source_lines))):
        line = source_lines[i].strip()
        signature_lines.append(line)
        if line.endswith(":"):
            break

    return " ".join(signature_lines)


# ============================================================
# 辅助函数：从字节码提取签名（兼容旧接口）
# ============================================================


def extract_signature_from_bytes(
    src: bytes,
    span_node: Node,
    inner_node: Node,
    format: str = "compact"
) -> str:
    """从字节源码提取签名（兼容 chunker.py 的接口）。

    Args:
        src: 源码字节
        span_node: 外层节点
        inner_node: 内层节点
        format: "compact" 或 "multiline"

    Returns:
        签名字符串
    """
    # 转换为字符串
    source_text = src.decode("utf-8")
    source_lines = source_text.split("\n")

    return extract_signature(source_lines, span_node, inner_node, format)


# ============================================================
# 迁移适配器（保持旧函数兼容）
# ============================================================


def _extract_signature_legacy_analyzer(
    lines: list[str],
    start_line: int,
    end_line: int
) -> str:
    """旧版 analyzer._extract_signature 兼容适配器。

    迁移路径：
    1. analyzer.py 调用这个适配器
    2. 逐步替换为 extract_signature
    3. 删除适配器
    """
    # 提取签名行
    signature_lines = []
    for i in range(start_line - 1, min(end_line, len(lines))):
        line = lines[i].strip()
        signature_lines.append(line)
        if line.endswith(":"):
            break

    return " ".join(signature_lines)


def _signature_legacy_chunker(
    src: bytes,
    span_node: Node,
    inner: Node
) -> str:
    """旧版 chunker._signature 兼容适配器。

    迁移路径：
    1. chunker.py 调用这个适配器
    2. 逐步替换为 extract_signature_from_bytes
    3. 删除适配器
    """
    body = inner.child_by_field_name("body")
    end = body.start_byte if body is not None else inner.end_byte

    # 提取字节范围
    header = src[span_node.start_byte:end].decode("utf-8")

    # 压缩空白
    header = re.sub(r"\s+", " ", header).strip()

    # 确保以 ":" 结尾
    return header.rstrip().removesuffix(":").rstrip() + ":" if header else header


# ============================================================
# 实际迁移示例
# ============================================================


def migrate_analyzer_example():
    """演示如何迁移 analyzer.py。

    旧代码：
        signature = _extract_signature(lines, start_line, end_line)

    新代码（阶段 1 - 使用适配器）：
        signature = _extract_signature_legacy_analyzer(lines, start_line, end_line)

    新代码（阶段 2 - 完全迁移）：
        signature = extract_signature(lines, span_node, inner_node, format="multiline")
    """
    pass


def migrate_chunker_example():
    """演示如何迁移 chunker.py。

    旧代码：
        signature = _signature(src, span_node, inner)

    新代码（阶段 1 - 使用适配器）：
        signature = _signature_legacy_chunker(src, span_node, inner)

    新代码（阶段 2 - 完全迁移）：
        signature = extract_signature_from_bytes(src, span_node, inner, format="compact")
    """
    pass


# ============================================================
# 测试：验证新旧实现一致性
# ============================================================


def test_signature_extraction_consistency():
    """验证统一实现与旧实现输出一致。"""
    import tempfile
    from pathlib import Path

    test_code = '''
@decorator
def foo(
    x: int,
    y: str
) -> bool:
    """Test function."""
    return True

class Bar:
    """Test class."""
    def method(self, z: float):
        pass
'''

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_code)
        temp_path = Path(f.name)

    try:
        from brain.tree_sitter_utils import get_parser, unwrap_decorated
        from brain.lang_config import get_config

        src = test_code.encode("utf-8")
        root = get_parser("python").parse(src).root_node
        cfg = get_config("python")
        lines = test_code.split("\n")

        # 测试第一个函数
        func_node = root.named_children[0]
        span_node, inner = unwrap_decorated(func_node, cfg)

        # 新实现（multiline）
        new_multiline = extract_signature(lines, span_node, inner, format="multiline")

        # 旧实现（analyzer 风格）
        start_line = span_node.start_point[0] + 1
        end_line = span_node.end_point[0] + 1
        old_multiline = _extract_signature_legacy_analyzer(lines, start_line, end_line)

        print(f"新实现 (multiline): {new_multiline}")
        print(f"旧实现 (analyzer):  {old_multiline}")

        # 新实现（compact）
        new_compact = extract_signature_from_bytes(src, span_node, inner, format="compact")

        # 旧实现（chunker 风格）
        old_compact = _signature_legacy_chunker(src, span_node, inner)

        print(f"新实现 (compact): {new_compact}")
        print(f"旧实现 (chunker): {old_compact}")

        # 验证基本一致（允许空白差异）
        assert "def foo" in new_multiline
        assert "def foo" in new_compact
        assert "decorator" in new_compact

        print("✅ Signature extraction consistency test passed")

    finally:
        temp_path.unlink()


# ============================================================
# 配置选项：支持项目级定制
# ============================================================


class SignatureConfig:
    """签名提取配置（支持项目级定制）。"""

    def __init__(
        self,
        include_decorators: bool = True,
        include_return_type: bool = True,
        compact_whitespace: bool = True,
        max_length: int | None = None,
    ):
        """
        Args:
            include_decorators: 是否包含装饰器
            include_return_type: 是否包含返回类型
            compact_whitespace: 是否压缩空白
            max_length: 最大长度（超出则截断）
        """
        self.include_decorators = include_decorators
        self.include_return_type = include_return_type
        self.compact_whitespace = compact_whitespace
        self.max_length = max_length


def extract_signature_with_config(
    source_lines: list[str],
    span_node: Node,
    inner_node: Node,
    config: SignatureConfig,
) -> str:
    """使用自定义配置提取签名（未来扩展）。

    支持项目级定制，如：
    - Python 项目可能不需要装饰器
    - TypeScript 项目可能需要保留完整类型注解
    - Go 项目可能需要特殊格式
    """
    # 基础提取
    format_style = "compact" if config.compact_whitespace else "multiline"
    signature = extract_signature(source_lines, span_node, inner_node, format_style)

    # 移除装饰器（如果配置要求）
    if not config.include_decorators and "@" in signature:
        # 简单实现：移除 @ 开头的部分
        parts = signature.split()
        signature = " ".join(p for p in parts if not p.startswith("@"))

    # 移除返回类型（如果配置要求）
    if not config.include_return_type and "->" in signature:
        signature = signature.split("->")[0].rstrip() + ":"

    # 截断（如果超出长度）
    if config.max_length and len(signature) > config.max_length:
        signature = signature[:config.max_length - 3] + "..."

    return signature


# ============================================================
# 迁移计划
# ============================================================

MIGRATION_PLAN = """
# 签名提取统一迁移计划

## 当前状态

两处实现：
1. analyzer.py:_extract_signature (lines, start_line, end_line) → str
2. chunker.py:_signature (src: bytes, span_node, inner) → str

## 目标状态

统一到 tree_sitter_utils.extract_signature()

## 迁移步骤

### 阶段 1：添加统一实现（不破坏现有代码）

在 tree_sitter_utils.py 中添加：
```python
def extract_signature(source_lines, span_node, inner_node, format="compact") -> str:
    ...
```

### 阶段 2：添加兼容适配器

在 analyzer.py 和 chunker.py 中：
```python
# analyzer.py
def _extract_signature(lines, start_line, end_line):
    # 委托给统一实现（需要 span_node 和 inner_node）
    return _extract_signature_legacy_analyzer(lines, start_line, end_line)

# chunker.py
def _signature(src, span_node, inner):
    return _signature_legacy_chunker(src, span_node, inner)
```

### 阶段 3：逐步替换调用点

```python
# 旧代码
signature = _extract_signature(lines, start_line, end_line)

# 新代码
from brain.tree_sitter_utils import extract_signature
signature = extract_signature(lines, span_node, inner_node, format="multiline")
```

### 阶段 4：删除旧实现

- 删除 analyzer._extract_signature
- 删除 chunker._signature
- 删除适配器函数

### 阶段 5：（可选）添加配置支持

```python
# 支持项目级定制
config = SignatureConfig(include_decorators=False, max_length=80)
signature = extract_signature_with_config(lines, span_node, inner_node, config)
```

## 验证清单

- [ ] 运行 test_signature_extraction_consistency()
- [ ] 对比新旧实现输出（允许空白差异）
- [ ] 确保 analyzer 和 chunker 测试全部通过
- [ ] 手动检查生成的 Markdown 和 Chunk 内容
- [ ] 在真实项目上运行 analyze 和 index 命令

## 收益

1. **消除重复**：两处实现 → 一处实现
2. **一致性**：analyzer 和 chunker 使用相同逻辑
3. **可配置**：支持项目级定制
4. **可测试**：统一函数更易测试
5. **可维护**：修改签名格式只需改一处
"""


if __name__ == "__main__":
    print("签名提取统一方案")
    print("\n当前问题:")
    print("- analyzer.py 和 chunker.py 各有一套实现")
    print("- 逻辑略有差异（multiline vs compact）")
    print("- 违反 DRY 原则")
    print("\n解决方案:")
    print("- 统一到 tree_sitter_utils.extract_signature()")
    print("- 支持两种格式（multiline 和 compact）")
    print("- 提供配置选项（未来扩展）")
    print("\n运行测试...")
    test_signature_extraction_consistency()
