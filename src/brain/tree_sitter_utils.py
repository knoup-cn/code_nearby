"""共享 tree-sitter 工具函数。

从 chunker.py 提取，供 analyzer.py 和 chunker.py 共同使用。
所有与解析器、CST 遍历、文本提取相关的通用逻辑集中在此。
"""

from __future__ import annotations

import importlib
import re
import textwrap
from functools import cache
from pathlib import Path

from tree_sitter import Language, Node, Parser

from brain.lang_config import (  # 内部使用
    LanguageConfig,  # noqa: F401  类型标注用
    get_config,
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


def extract_parameters(func_node: Node, src: bytes) -> list[str]:
    """提取函数参数列表（含类型注解和默认值）。

    示例: ["self", "x: int", "y = 1"]
    """
    params = func_node.child_by_field_name("parameters")
    if params is None:
        return []
    args: list[str] = []
    for child in params.named_children:
        # 跳过分隔符和标点
        if child.type in (",", "(", ")", "=>", "*/", "*"):
            continue
        args.append(node_text(src, child))
    return args


def extract_return_type(func_node: Node, src: bytes) -> str | None:
    """提取函数返回类型注解文本，无则返回 None。"""
    rt = func_node.child_by_field_name("return_type")
    return node_text(src, rt) if rt is not None else None


def extract_base_classes(class_node: Node, src: bytes) -> list[str]:
    """提取基类/父类名称列表。"""
    superclasses = class_node.child_by_field_name("superclasses")
    if superclasses is None:
        return []
    return [
        node_text(src, c)
        for c in superclasses.named_children
        if c.type not in (",", "(", ")", ":", "extends", "implements")
    ]


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


def first_string(src: bytes, block: Node) -> str | None:
    """提取代码块第一条语句中的字符串字面量（Python docstring 模式）。

    docstring 必须是 block 的第一个语句。
    """
    for child in block.named_children:
        if child.type == "expression_statement" and child.named_child_count:
            inner = child.named_children[0]
            if inner.type == "string":
                return clean_string(src, inner)
        break  # docstring 必须是第一条语句
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
                dotted = _dotted_name(src, n)
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


def _dotted_name(src: bytes, node: Node) -> str:
    """从 import 节点提取点分名称。"""
    if node.type == "dotted_name":
        return node_text(src, node)
    if node.type == "aliased_import":
        target = node.child_by_field_name("name")
        return node_text(src, target) if target is not None else ""
    return ""
