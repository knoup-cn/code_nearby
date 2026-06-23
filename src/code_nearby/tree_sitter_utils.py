"""共享 tree-sitter 工具函数——解析器、CST 遍历、文本提取、import 收集、签名提取。"""

from __future__ import annotations

import importlib
import re
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from tree_sitter import Language, Node, Parser

from brain.lang_config import (  # 内部使用
    LanguageConfig,  # noqa: F401  类型标注用
    get_config,
)


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    """tree-sitter 遍历产出的单个代码符号（函数/方法/类）。

    保留 ``span_node`` 和 ``inner_node`` 让消费者自行按需提取数据
    （args、return_type、bases、content），避免此结构成为大杂烩。
    Node 内存安全——rooted in tree-sitter Tree，调用者保活。
    """

    name: str
    kind: str  # "function" / "method" / "class"
    scope: tuple[str, ...]  # 父级 scope 路径，如 ("ClassName",)
    span_node: Node  # 含装饰器的完整 span 节点
    inner_node: Node  # 实际 def/class 声明节点
    start_line: int  # 1-indexed，含装饰器
    end_line: int  # 1-indexed
    is_private: bool
    is_async: bool


def walk_symbols(
    scope_node: Node,
    src: bytes,
    cfg: LanguageConfig,
    scope: tuple[str, ...] = (),
    parent_class: str | None = None,
) -> Iterator[SymbolInfo]:
    """递归遍历 CST scope 节点，产出每个函数/方法/类的 :class:`SymbolInfo`。

    这是 chunker 和 graph 的**共享 CST 遍历**。
    调用者通过 ``SymbolInfo`` 的 ``span_node`` / ``inner_node`` 字段
    按需调用 ``extract_signature``、``get_docstring`` 等 helper。

    Args:
        scope_node: 起始 scope 的 CST 节点（通常为 root_node 或类 body）
        src: 源文件字节
        cfg: 语言配置
        scope: 当前 scope 路径（递归参数，调用者不传）
        parent_class: 当前所属类名（递归参数，调用者不传）
    """
    is_class_body = scope_node.type in cfg.class_types
    body = scope_node.child_by_field_name("body") if is_class_body else scope_node
    if body is None:
        return

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

        if inner.type in func_types:
            kind = "method" if parent_class else "function"
            yield SymbolInfo(
                name=name,
                kind=kind,
                scope=scope,
                span_node=span_node,
                inner_node=inner,
                start_line=span_node.start_point[0] + 1,
                end_line=span_node.end_point[0] + 1,
                is_private=cfg.is_private_symbol(name),
                is_async=is_async_def(inner) if cfg.has_async_keyword else False,
            )
        elif inner.type in cfg.class_types:
            yield SymbolInfo(
                name=name,
                kind="class",
                scope=scope,
                span_node=span_node,
                inner_node=inner,
                start_line=span_node.start_point[0] + 1,
                end_line=span_node.end_point[0] + 1,
                is_private=cfg.is_private_symbol(name),
                is_async=False,
            )
            # 递归进入类体
            yield from walk_symbols(
                inner,
                src,
                cfg,
                scope=(*scope, name),
                parent_class=name,
            )


# ======================================================================
# 解析器工厂
# ======================================================================


@cache
def get_parser(language: str) -> Parser:
    """返回指定语言的缓存 parser（使用内置 grammar，不下载）。"""
    cfg = get_config(language)
    mod = importlib.import_module(cfg.grammar_module)
    grammar_fn = getattr(mod, cfg.grammar_attr)
    return Parser(Language(grammar_fn()))


# ======================================================================
# 源码切片
# ======================================================================


def node_text(src: bytes, node: Node) -> str:
    """节点对应的源码文本。"""
    return node_slice(src, node.start_byte, node.end_byte)


def node_slice(src: bytes, start: int, end: int) -> str:
    """字节范围的源码文本，去除末尾空白。"""
    return src[start:end].decode("utf-8", errors="replace").rstrip()


def relative_path(file_path: Path, project_root: Path) -> str:
    """仓库根目录下的相对 posix 路径，解析失败则回退到文件名。"""
    try:
        return file_path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return file_path.name


# ======================================================================
# 节点字段提取
# ======================================================================


def node_name(node: Node, src: bytes) -> str:
    """提取节点的 name 字段（函数/类名）。"""
    name_node = node.child_by_field_name("name")
    return node_text(src, name_node) if name_node is not None else ""


def is_async_def(node: Node) -> bool:
    """判断函数/方法定义是否包含 async 关键字。"""
    return any(child.type == "async" for child in node.children)



# ======================================================================
# 装饰器处理
# ======================================================================


def unwrap_decorated(node: Node, cfg: LanguageConfig) -> tuple[Node, Node]:
    """解开 wrapper 节点（decorated_definition / export_statement 等）。

    返回 (span_node, inner_def)。span_node 包含 wrapper 节点（装饰器行等），
    inner 是实际的函数/类声明节点。
    对于非 wrapper 节点直接返回 (node, node)。
    """
    # 处理 decorated_definition（Python 装饰器）
    decorated_type = cfg.decorated_type
    if decorated_type is not None and node.type == decorated_type:
        inner = node.child_by_field_name("definition")
        return node, inner if inner is not None else node

    # 处理 export_statement 等通用 wrapper
    if node.type in cfg.wrapper_types and node.named_child_count > 0:
        # 取第一个 named child 作为实际声明体
        inner = node.named_children[0]
        return node, inner

    return node, node


# ======================================================================
# Docstring 提取
# ======================================================================


def get_docstring(src: bytes, node: Node) -> str | None:
    """函数/类的 docstring。"""
    body = node.child_by_field_name("body")
    return first_string(src, body) if body is not None else None


def get_module_docstring(src: bytes, root: Node) -> str | None:
    """模块级 docstring。"""
    return first_string(src, root)


# 框架 pragma 指令（非 docstring，应跳过）
_PRAGMA_DIRECTIVES = frozenset({"use client", "use server", "use strict"})


def _is_framework_pragma(text: str) -> bool:
    """检查字符串是否为框架 pragma 指令（如 'use client'、'use strict'）。"""
    return text.strip().lower() in _PRAGMA_DIRECTIVES


def first_string(src: bytes, block: Node) -> str | None:
    """提取代码块第一条语句中的字符串字面量（Python docstring 模式）。

    跳过框架 pragma 指令（'use client'、'use server'、'use strict'），
    这些是指令而非文档。docstring 必须是第一个非 pragma 语句。
    """
    for child in block.named_children:
        if child.type == "expression_statement" and child.named_child_count:
            inner = child.named_children[0]
            if inner.type == "string":
                text = clean_string(src, inner)
                if _is_framework_pragma(text):
                    continue  # 跳过 pragma，检查下一个语句
                return text
        break  # 第一个非字符串语句意味着没有 docstring
    return None


def clean_string(src: bytes, string_node: Node) -> str:
    """去除 docstring 的引号和前缀，dedent 并 strip。"""
    for c in string_node.named_children:
        if c.type == "string_content":
            return dedent(node_text(src, c))
    # 回退：手动去除引号
    raw = node_text(src, string_node)
    raw = re.sub(r'^[a-zA-Z]*("""|\'\'\'|"|\')', "", raw)
    raw = re.sub(r'("""|\'\'\'|"|\')$', "", raw)
    return dedent(raw)


def dedent(text: str) -> str:
    """去除公共缩进并 strip。"""
    return textwrap.dedent(text).strip()


# ======================================================================
# Import 收集
# ======================================================================


def collect_imports(src: bytes, root: Node, language: str) -> tuple[str, ...]:
    """收集模块顶层 import 的模块名（去重，保持顺序）。

    目前仅完整支持 Python；其他语言返回空元组（后续扩展）。
    """
    if language == "python":
        return _collect_python_imports(src, root)
    # TODO: JS/TS/Go/Rust import 收集
    return ()


def _collect_python_imports(src: bytes, root: Node) -> tuple[str, ...]:
    """收集 Python 顶层 import 的模块名。"""
    names: list[str] = []
    for child in root.named_children:
        if child.type == "import_statement":
            for n in child.named_children:
                dotted = dotted_name(src, n)
                if dotted:
                    names.append(dotted)
        elif child.type == "import_from_statement":
            module = child.child_by_field_name("module_name")
            if module is not None:
                dotted = node_text(src, module)
                if dotted:
                    names.append(dotted)
    # 去重，保持顺序
    seen: set[str] = set()
    return tuple(n for n in names if not (n in seen or seen.add(n)))


def dotted_name(src: bytes, node: Node) -> str:
    """从 import 节点提取点分名称。"""
    if node.type == "dotted_name":
        return node_text(src, node)
    if node.type == "aliased_import":
        target = node.child_by_field_name("name")
        return node_text(src, target) if target is not None else ""
    return ""


# ======================================================================
# 签名提取（统一实现）
# ======================================================================


def extract_signature(
    source_lines: list[str],
    span_node: Node,
    inner_node: Node,
) -> str:
    """提取函数/类签名，压缩空白为单行。

    使用 body 子节点确定签名结束位置，适配所有语言：
    - Python：签名以 ':' 结尾，body 从下一行开始
    - TS/JS/Go/Rust：签名以 '{' 结尾，body 可能同行或下一行
    """
    start_line = span_node.start_point[0]

    body = inner_node.child_by_field_name("body")
    if body is not None:
        sig_end = body.start_point[0]
        sig_end = max(sig_end, start_line + 1)
    else:
        sig_end = inner_node.end_point[0] + 1

    signature_lines = []
    for i in range(start_line, min(sig_end, len(source_lines))):
        line = source_lines[i].strip()
        signature_lines.append(line)

    header = " ".join(signature_lines)
    header = re.sub(r"\s+", " ", header).strip()

    return header if header else ""
