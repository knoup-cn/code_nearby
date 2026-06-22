"""重构方案 2：统一符号提取逻辑

消除 analyzer.py 和 chunker.py 之间 100+ 行重复代码。
采用访问者模式 + 统一遍历器。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tree_sitter import Node

from brain.lang_config import LanguageConfig
from brain.tree_sitter_utils import (
    extract_base_classes,
    extract_parameters,
    extract_return_type,
    get_docstring,
    is_async_def,
    node_name,
    node_text,
    unwrap_decorated,
)


# ============================================================
# 核心抽象：符号信息（统一数据模型）
# ============================================================


@dataclass
class SymbolInfo:
    """符号的统一表示（函数、类、方法）。

    analyzer 和 chunker 都基于这个模型工作，避免重复提取。
    """
    name: str
    symbol_type: str  # "function" | "class" | "method"
    start_line: int
    end_line: int
    signature: str
    docstring: str | None
    is_private: bool
    is_async: bool

    # Function/Method specific
    args: list[str] | None = None
    return_type: str | None = None

    # Class specific
    bases: list[str] | None = None
    methods: list[SymbolInfo] | None = None

    # Source info
    span_node: Node | None = None  # 保留 AST 节点供高级处理


# ============================================================
# 访问者协议：不同模块实现自己的处理逻辑
# ============================================================


class SymbolVisitor(Protocol):
    """符号访问者协议。

    analyzer 和 chunker 各自实现这个接口：
    - analyzer: 累积到 dict 中，生成文档
    - chunker: 创建 Chunk 对象
    """

    def visit_function(self, info: SymbolInfo) -> None:
        """处理函数符号。"""
        ...

    def visit_class(self, info: SymbolInfo) -> None:
        """处理类符号。"""
        ...

    def visit_method(self, info: SymbolInfo, parent_class: str) -> None:
        """处理方法符号。"""
        ...


# ============================================================
# 统一遍历器：核心逻辑只写一次
# ============================================================


def walk_symbols(
    root: Node,
    src: bytes,
    source: str,
    cfg: LanguageConfig,
    visitor: SymbolVisitor,
) -> None:
    """遍历顶层符号并回调 visitor（analyzer 和 chunker 共用）。

    Args:
        root: AST 根节点
        src: 源文件字节
        source: 源文件字符串
        cfg: 语言配置
        visitor: 符号处理器
    """
    _walk_scope(
        scope_node=root,
        src=src,
        source=source,
        cfg=cfg,
        visitor=visitor,
        scope=[],
        parent_class=None,
    )


def _walk_scope(
    scope_node: Node,
    src: bytes,
    source: str,
    cfg: LanguageConfig,
    visitor: SymbolVisitor,
    scope: list[str],
    parent_class: str | None,
) -> None:
    """递归遍历作用域内的符号（内部实现）。"""
    is_class = scope_node.type in cfg.class_types
    body = scope_node.child_by_field_name("body") if is_class else scope_node
    if body is None:
        return

    # 构建符号类型集合
    func_types = {cfg.func_type}
    if cfg.method_func_types:
        func_types.update(cfg.method_func_types)

    symbol_types = func_types | set(cfg.class_types) | set(cfg.wrapper_types)
    if cfg.decorated_type:
        symbol_types.add(cfg.decorated_type)

    for child in body.named_children:
        if child.type not in symbol_types:
            continue

        span_node, inner = unwrap_decorated(child, cfg)
        if inner is None:
            continue

        name = node_name(inner, src)
        if not name:
            continue

        qualified_name = ".".join([*scope, name])

        # ---- 函数/方法 ----
        if inner.type in func_types:
            info = _extract_function_info(
                span_node, inner, src, source, cfg, qualified_name, parent_class
            )
            if parent_class:
                visitor.visit_method(info, parent_class)
            else:
                visitor.visit_function(info)

        # ---- 类 ----
        elif inner.type in cfg.class_types:
            info = _extract_class_info(
                span_node, inner, src, source, cfg, qualified_name, parent_class
            )
            visitor.visit_class(info)

            # 递归处理类内符号
            _walk_scope(
                scope_node=inner,
                src=src,
                source=source,
                cfg=cfg,
                visitor=visitor,
                scope=[*scope, name],
                parent_class=name,
            )


def _extract_function_info(
    span_node: Node,
    inner: Node,
    src: bytes,
    source: str,
    cfg: LanguageConfig,
    qualified_name: str,
    parent_class: str | None,
) -> SymbolInfo:
    """从 AST 节点提取函数信息（统一实现）。"""
    lines = source.split("\n")
    start_line = span_node.start_point[0] + 1
    end_line = span_node.end_point[0] + 1
    name = node_name(inner, src)

    return SymbolInfo(
        name=name,
        symbol_type="method" if parent_class else "function",
        start_line=start_line,
        end_line=end_line,
        signature=_extract_signature(lines, start_line, end_line),
        docstring=get_docstring(src, inner),
        is_private=cfg.is_private_symbol(name),
        is_async=is_async_def(inner) if cfg.has_async_keyword else False,
        args=extract_parameters(inner, src),
        return_type=extract_return_type(inner, src),
        span_node=span_node,
    )


def _extract_class_info(
    span_node: Node,
    inner: Node,
    src: bytes,
    source: str,
    cfg: LanguageConfig,
    qualified_name: str,
    parent_class: str | None,
) -> SymbolInfo:
    """从 AST 节点提取类信息（统一实现）。"""
    lines = source.split("\n")
    start_line = span_node.start_point[0] + 1
    end_line = span_node.end_point[0] + 1
    name = node_name(inner, src)

    return SymbolInfo(
        name=name,
        symbol_type="class",
        start_line=start_line,
        end_line=end_line,
        signature=_extract_signature(lines, start_line, end_line),
        docstring=get_docstring(src, inner),
        is_private=cfg.is_private_symbol(name),
        is_async=False,
        bases=extract_base_classes(inner, src),
        methods=[],  # 由 visitor 在遍历时填充
        span_node=span_node,
    )


def _extract_signature(lines: list[str], start_line: int, end_line: int) -> str:
    """提取函数/类签名（统一实现，替代两处重复代码）。

    Args:
        lines: 源码行列表
        start_line: 起始行号（1-indexed）
        end_line: 结束行号（1-indexed）

    Returns:
        签名文本（如 "def analyze_file(...):"）
    """
    signature_lines = []
    for i in range(start_line - 1, min(end_line, len(lines))):
        line = lines[i].strip()
        signature_lines.append(line)
        if line.endswith(":"):
            break
    return " ".join(signature_lines)


# ============================================================
# Analyzer 适配器：符号 → 文档结构
# ============================================================


class AnalyzerVisitor:
    """Analyzer 模块的访问者实现。

    累积符号到 dict 中，供文档生成使用。
    """

    def __init__(self):
        self.functions: list[dict] = []
        self.classes: list[dict] = []
        self._current_class: dict | None = None

    def visit_function(self, info: SymbolInfo) -> None:
        """顶层函数 → 加入 functions 列表。"""
        self.functions.append({
            "name": info.name,
            "lineno": info.start_line,
            "end_lineno": info.end_line,
            "docstring": info.docstring,
            "args": info.args or [],
            "return_type": info.return_type,
            "is_private": info.is_private,
            "is_async": info.is_async,
            "signature": info.signature,
            "signature_hash": self._compute_hash(info.signature),
        })

    def visit_class(self, info: SymbolInfo) -> None:
        """类 → 加入 classes 列表，记录为 current_class。"""
        class_dict = {
            "name": info.name,
            "lineno": info.start_line,
            "end_lineno": info.end_line,
            "docstring": info.docstring,
            "methods": [],
            "bases": info.bases or [],
            "is_private": info.is_private,
            "signature": info.signature,
            "signature_hash": self._compute_hash(info.signature),
        }
        self.classes.append(class_dict)
        self._current_class = class_dict

    def visit_method(self, info: SymbolInfo, parent_class: str) -> None:
        """方法 → 加入当前类的 methods 列表。"""
        if self._current_class is None:
            return

        self._current_class["methods"].append({
            "name": info.name,
            "lineno": info.start_line,
            "end_lineno": info.end_line,
            "docstring": info.docstring,
            "args": info.args or [],
            "return_type": info.return_type,
            "is_private": info.is_private,
            "is_async": info.is_async,
            "signature": info.signature,
            "signature_hash": self._compute_hash(info.signature),
        })

    def get_symbols(self) -> dict[str, list[dict]]:
        """返回 analyzer 期望的 dict 格式。"""
        return {
            "functions": self.functions,
            "classes": self.classes,
        }

    @staticmethod
    def _compute_hash(signature: str) -> str:
        """计算签名哈希（从 analyzer.py 迁移）。"""
        import hashlib
        normalized = signature.strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:8]


# ============================================================
# Chunker 适配器：符号 → Chunk 对象
# ============================================================


class ChunkerVisitor:
    """Chunker 模块的访问者实现。

    将符号转换为 Chunk 对象。
    """

    def __init__(self, builder):
        """
        Args:
            builder: _ChunkBuilder 实例（已包含 rel_path, language, imports 等上下文）
        """
        self.builder = builder
        self._parent_class: str | None = None

    def visit_function(self, info: SymbolInfo) -> None:
        """顶层函数 → 创建 function chunk。"""
        chunk = self.builder.make(
            chunk_type="function",
            symbol=info.name,
            qualified_name=info.name,
            parent_class=None,
            start_line=info.start_line,
            end_line=info.end_line,
            signature=info.signature,
            docstring=info.docstring,
            content=node_text(self.builder.src, info.span_node),
        )
        self.builder.add(chunk)

    def visit_class(self, info: SymbolInfo) -> None:
        """类 → 创建 class chunk（仅包含 preamble）。"""
        # 提取类 preamble（头部到第一个方法之前）
        from brain.rag.chunker import _class_preamble_end
        from brain.lang_config import get_config

        cfg = get_config(self.builder.language)
        preamble_end = _class_preamble_end(info.span_node, cfg)
        content = self.builder.src[info.span_node.start_byte:preamble_end].decode("utf-8")
        end_line = info.start_line + content.count("\n")

        chunk = self.builder.make(
            chunk_type="class",
            symbol=info.name,
            qualified_name=info.name,
            parent_class=self._parent_class,
            start_line=info.start_line,
            end_line=end_line,
            signature=info.signature,
            docstring=info.docstring,
            content=content,
        )
        self.builder.add(chunk)
        self._parent_class = info.name

    def visit_method(self, info: SymbolInfo, parent_class: str) -> None:
        """方法 → 创建 method chunk。"""
        chunk = self.builder.make(
            chunk_type="method",
            symbol=info.name,
            qualified_name=f"{parent_class}.{info.name}",
            parent_class=parent_class,
            start_line=info.start_line,
            end_line=info.end_line,
            signature=info.signature,
            docstring=info.docstring,
            content=node_text(self.builder.src, info.span_node),
        )
        self.builder.add(chunk)


# ============================================================
# 迁移路径：渐进式替换
# ============================================================


def migrate_analyzer():
    """analyzer.py 的迁移示例。

    原代码：
        symbols = _extract_symbols(root, src, source, cfg)

    新代码：
        visitor = AnalyzerVisitor()
        walk_symbols(root, src, source, cfg, visitor)
        symbols = visitor.get_symbols()
    """
    pass


def migrate_chunker():
    """chunker.py 的迁移示例。

    原代码：
        _walk_scope(root, scope=[], parent_class=None, builder=builder, cfg=cfg)

    新代码：
        visitor = ChunkerVisitor(builder)
        walk_symbols(root, src, source, cfg, visitor)
    """
    pass


# ============================================================
# 测试验证
# ============================================================


def test_visitor_equivalence():
    """验证新旧实现输出一致。

    测试策略：
    1. 对同一文件运行旧版和新版
    2. 比较输出的符号列表（忽略顺序）
    3. 确保 100% 一致后再删除旧代码
    """
    import tempfile
    from pathlib import Path

    test_code = '''
def foo(x: int) -> str:
    """Test function."""
    return str(x)

class Bar:
    """Test class."""
    def method(self):
        """Test method."""
        pass
'''

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_code)
        temp_path = Path(f.name)

    try:
        # 旧版实现（调用 analyzer._extract_symbols）
        from brain.analyzer import _extract_symbols
        from brain.lang_config import get_config
        from brain.tree_sitter_utils import get_parser

        src = test_code.encode("utf-8")
        root = get_parser("python").parse(src).root_node
        cfg = get_config("python")

        old_symbols = _extract_symbols(root, src, test_code, cfg)

        # 新版实现
        visitor = AnalyzerVisitor()
        walk_symbols(root, src, test_code, cfg, visitor)
        new_symbols = visitor.get_symbols()

        # 验证一致性
        assert len(old_symbols["functions"]) == len(new_symbols["functions"])
        assert len(old_symbols["classes"]) == len(new_symbols["classes"])
        assert old_symbols["functions"][0]["name"] == new_symbols["functions"][0]["name"]
        assert old_symbols["classes"][0]["name"] == new_symbols["classes"][0]["name"]

        print("✅ Visitor equivalence test passed")

    finally:
        temp_path.unlink()


if __name__ == "__main__":
    test_visitor_equivalence()
