"""代码分析操作——将源文件解析为 Obsidian 知识库文档。

使用 tree-sitter 做 CST 解析，支持 Python/JavaScript/TypeScript/Go/Rust。
输出 Obsidian 兼容的 Markdown（YAML frontmatter + wikilinks）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tree_sitter import Node

from brain.lang_config import LanguageConfig, detect_language, get_config
from brain.tree_sitter_utils import (
    extract_base_classes,
    extract_parameters,
    extract_return_type,
    get_docstring,
    get_module_docstring,
    get_parser,
    is_async_def,
    node_name,
    node_text,
    unwrap_decorated,
)


def analyze_file(file_path: Path, kb_path: Path, project_root: Path) -> None:
    """分析单个文件并写入知识库。

    Args:
        file_path: 待分析文件
        kb_path: 知识库根路径
        project_root: 项目根目录（用于计算相对路径）
    """
    language = detect_language(file_path)
    if language is None:
        return

    try:
        source = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return

    cfg = get_config(language)
    src = source.encode("utf-8")
    root = get_parser(language).parse(src).root_node

    # 提取结构信息
    relative = file_path.relative_to(project_root)
    project_name = project_root.resolve().name
    metadata = _extract_metadata(file_path, relative, root, src, source, cfg)
    symbols = _extract_symbols(root, src, source, cfg)
    dependencies = _extract_dependencies(root, src, project_name)

    # 生成 Obsidian 兼容 Markdown
    content = _generate_obsidian_md(
        file_path=file_path,
        relative_path=relative,
        metadata=metadata,
        symbols=symbols,
        dependencies=dependencies,
        project_name=project_name,
    )

    # 写入知识库。内容与磁盘相同时跳过写入，避免无意义的 git churn
    kb_file = kb_path / relative.with_suffix(".md")
    if kb_file.exists() and kb_file.read_text(encoding="utf-8") == content:
        return
    kb_file.parent.mkdir(parents=True, exist_ok=True)
    kb_file.write_text(content, encoding="utf-8")


def _extract_metadata(
    file_path: Path,
    relative_path: Path,
    root: Node,
    src: bytes,
    source: str,
    cfg: LanguageConfig,
) -> dict[str, Any]:
    """提取文件级元数据。"""
    module_docstring = get_module_docstring(src, root)

    # 统计代码行（排除空行和注释行）
    lines = source.split("\n")
    comment_prefix = cfg.comment_prefix
    code_lines = [
        line
        for line in lines
        if line.strip() and not line.strip().startswith(comment_prefix)
    ]

    return {
        "type": cfg.module_type_label,
        "path": str(relative_path),
        "module_docstring": module_docstring,
        "lines_of_code": len(code_lines),
    }


def _extract_symbols(
    root: Node,
    src: bytes,
    source: str,
    cfg: LanguageConfig,
) -> dict[str, list[dict[str, Any]]]:
    """从顶层提取函数和类。

    Args:
        root: CST 根节点
        src: 源文件字节
        source: 源文件字符串（用于提取签名行）
        cfg: 语言配置

    Returns:
        包含 'functions' 和 'classes' 列表的字典
    """
    symbols: dict[str, list[dict[str, Any]]] = {"functions": [], "classes": []}
    lines = source.split("\n")

    # 方法节点类型集合（None 表示与 func_type 相同）
    method_func_types = cfg.method_func_types or (cfg.func_type,)

    for node in root.named_children:
        span_node, inner = unwrap_decorated(node, cfg)

        # ---- 函数检测 ----
        if inner.type == cfg.func_type or (
            cfg.method_func_types and inner.type in cfg.method_func_types
        ):
            # 只有顶层函数才加入 functions 列表（方法在类内部处理）
            name = node_name(inner, src)
            is_async = is_async_def(inner) if cfg.has_async_keyword else False

            # 提取参数
            args = extract_parameters(inner, src)

            # 提取返回类型
            return_type = extract_return_type(inner, src)

            # 从源码提取签名
            start_line = span_node.start_point[0] + 1
            end_line = span_node.end_point[0] + 1
            signature = _extract_signature(lines, start_line, end_line)
            signature_hash = _compute_signature_hash(signature)

            symbols["functions"].append(
                {
                    "name": name,
                    "lineno": start_line,
                    "end_lineno": end_line,
                    "docstring": get_docstring(src, inner),
                    "args": args,
                    "return_type": return_type,
                    "is_private": cfg.is_private_symbol(name),
                    "is_async": is_async,
                    "signature": signature,
                    "signature_hash": signature_hash,
                }
            )

        # ---- 类检测 ----
        elif inner.type in cfg.class_types:
            name = node_name(inner, src)
            bases = extract_base_classes(inner, src)

            # 提取类体内的方法
            methods = []
            body = inner.child_by_field_name("body")
            if body is not None:
                for child in body.named_children:
                    m_span, m_inner = unwrap_decorated(child, cfg)
                    if m_inner.type not in method_func_types:
                        continue
                    m_name = node_name(m_inner, src)
                    if not m_name:
                        continue
                    m_is_async = is_async_def(m_inner) if cfg.has_async_keyword else False
                    m_args = extract_parameters(m_inner, src)
                    m_return_type = extract_return_type(m_inner, src)
                    m_start = m_span.start_point[0] + 1
                    m_end = m_span.end_point[0] + 1
                    m_sig = _extract_signature(lines, m_start, m_end)
                    m_sig_hash = _compute_signature_hash(m_sig)

                    methods.append(
                        {
                            "name": m_name,
                            "lineno": m_start,
                            "end_lineno": m_end,
                            "docstring": get_docstring(src, m_inner),
                            "args": m_args,
                            "return_type": m_return_type,
                            "is_private": cfg.is_private_symbol(m_name),
                            "is_async": m_is_async,
                            "signature": m_sig,
                            "signature_hash": m_sig_hash,
                        }
                    )

            start_line = span_node.start_point[0] + 1
            end_line = span_node.end_point[0] + 1
            signature = _extract_signature(lines, start_line, end_line)
            signature_hash = _compute_signature_hash(signature)

            symbols["classes"].append(
                {
                    "name": name,
                    "lineno": start_line,
                    "end_lineno": end_line,
                    "docstring": get_docstring(src, inner),
                    "methods": methods,
                    "bases": bases,
                    "is_private": cfg.is_private_symbol(name),
                    "signature": signature,
                    "signature_hash": signature_hash,
                }
            )

    return symbols


def _extract_signature(lines: list[str], start_line: int, end_line: int) -> str:
    """从源码提取函数/类签名。

    Args:
        lines: 源码行列表
        start_line: 起始行号（1-indexed）
        end_line: 结束行号（1-indexed）

    Returns:
        签名文本（如 "def analyze_file(...):"）
    """
    # 提取 def/class 行（可能跨多行）
    signature_lines = []
    for i in range(start_line - 1, min(end_line, len(lines))):
        line = lines[i].strip()
        signature_lines.append(line)
        # 遇到第一个以 ":" 结尾的行即停止
        if line.endswith(":"):
            break

    return " ".join(signature_lines)


def _compute_signature_hash(signature: str) -> str:
    """计算签名的 SHA256 哈希（前 8 个十六进制字符）。

    Args:
        signature: 函数/类签名

    Returns:
        8 字符的十六进制哈希
    """
    normalized = signature.strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:8]


def _extract_dependencies(
    root: Node,
    src: bytes,
    project_name: str,
) -> dict[str, list[str]]:
    """提取 import 和依赖。

    Args:
        root: CST 根节点
        src: 源文件字节
        project_name: 项目名称（用于检测内部 import）

    Returns:
        包含 'imports' 和 'internal_imports' 列表的字典
    """
    imports: list[str] = []
    internal_imports: list[str] = []

    for child in root.named_children:
        if child.type == "import_statement":
            for n in child.named_children:
                dotted = _dotted_name(src, n)
                if dotted:
                    imports.append(dotted)
                    # 检测内部 import（以项目名为前缀）
                    if dotted.startswith(f"{project_name}."):
                        internal_imports.append(dotted)

        elif child.type == "import_from_statement":
            module = child.child_by_field_name("module_name")
            if module is not None:
                mod_name = node_text(src, module)
                imports.append(mod_name)
                # 判断是否为内部 import
                if mod_name.startswith(f"{project_name}.") or mod_name == project_name:
                    if mod_name == project_name:
                        # from project import x, y → 展开为 project.x, project.y
                        # 跳过第一个 named_child（与 module_name 相同的 dotted_name）
                        inner_names = [
                            n
                            for n in child.named_children
                            if n.type in ("dotted_name", "aliased_import")
                        ]
                        for n in inner_names[1:]:  # 跳过第一个（module_name 自身）
                            name = _dotted_name(src, n)
                            if name:
                                internal_imports.append(f"{project_name}.{name}")
                    else:
                        internal_imports.append(mod_name)

    return {
        "imports": sorted(set(imports)),
        "internal_imports": sorted(set(internal_imports)),
    }


def _dotted_name(src: bytes, node: Node) -> str:
    """从 import 节点提取点分名称。"""
    if node.type == "dotted_name":
        return node_text(src, node)
    if node.type == "aliased_import":
        target = node.child_by_field_name("name")
        return node_text(src, target) if target is not None else ""
    return ""


def _infer_tags(
    relative_path: Path,
    symbols: dict[str, list[dict[str, Any]]],
    language: str,
) -> list[str]:
    """根据文件内容和路径自动推断标签。"""
    cfg = get_config(language)
    tags = [cfg.tag_name]

    # 基于路径
    parts = relative_path.parts
    if "tests" in parts or "test" in parts:
        tags.append("test")
    if "operations" in relative_path.stem:
        tags.append("core")
    if "cli" in relative_path.stem:
        tags.append("cli")
    if "tui" in relative_path.stem:
        tags.append("tui")

    # 基于内容
    if any(f["is_async"] for f in symbols["functions"]):
        tags.append("async")
    if any("test_" in f["name"] for f in symbols["functions"]):
        tags.append("test")

    return tags


def _generate_obsidian_md(
    file_path: Path,
    relative_path: Path,
    metadata: dict[str, Any],
    symbols: dict[str, list[dict[str, Any]]],
    dependencies: dict[str, list[str]],
    project_name: str,
) -> str:
    """生成 Obsidian 兼容的 Markdown（含 frontmatter 和 wikilinks）。

    Args:
        file_path: 源文件绝对路径
        relative_path: 相对于项目根目录的路径
        metadata: 文件元数据
        symbols: 提取的符号（函数、类）
        dependencies: import 依赖
        project_name: 项目名称（用于过滤内部 import）
    """
    module_name = relative_path.stem

    # 构建完整模块名（如 "brain.analyzer"）
    module_parts = []
    for part in relative_path.parts[:-1]:  # 排除文件名
        if part == "src":
            continue
        module_parts.append(part)
    module_parts.append(module_name)
    full_module_name = ".".join(module_parts)

    lines: list[str] = []

    # === Frontmatter（YAML）===
    lines.append("---")
    lines.append('brain_schema: "v1"')
    lines.append(f'type: {metadata["type"]}')
    lines.append(f'source_path: {metadata["path"]}')
    lines.append(f"module: {full_module_name}")

    # Exports（公开 API）
    exports = [f["name"] for f in symbols["functions"] if not f["is_private"]]
    exports += [c["name"] for c in symbols["classes"] if not c["is_private"]]
    if exports:
        lines.append("exports:")
        for exp in exports:
            lines.append(f"  - {exp}")

    # Dependencies（仅内部 wikilinks）
    if dependencies["internal_imports"]:
        lines.append("dependencies:")
        for imp in dependencies["internal_imports"]:
            link_name = imp.split(".")[-1]
            lines.append(f'  - "[[{link_name}]]"')

    # Symbols（含 signature_hash 和 location_hint）
    all_symbols = []
    for func in symbols["functions"]:
        all_symbols.append(func)
    for cls in symbols["classes"]:
        all_symbols.append(cls)

    if all_symbols:
        lines.append("symbols:")
        for sym in all_symbols:
            lines.append(f'  - name: {sym["name"]}')
            sym_type = "function" if "args" in sym else "class"
            lines.append(f"    type: {sym_type}")
            # 对 YAML 转义签名中的引号
            escaped_sig = sym["signature"].replace('"', '\\"')
            lines.append(f'    signature: "{escaped_sig}"')
            lines.append(f'    signature_hash: "{sym["signature_hash"]}"')
            lines.append(f'    location_hint: {sym["lineno"]}')
            lines.append(f'    is_private: {str(sym["is_private"]).lower()}')
            if sym_type == "function":
                lines.append(f'    is_async: {str(sym["is_async"]).lower()}')

    # Metrics
    lines.append(f'lines_of_code: {metadata["lines_of_code"]}')

    # Tags
    language = metadata["type"].split("-")[0] if "-" in metadata["type"] else "python"
    tags = _infer_tags(relative_path, symbols, language)
    lines.append(f"tags: [{', '.join(tags)}]")

    lines.append("---")
    lines.append("")

    # === 标题 ===
    lines.append(f"# {module_name}")
    lines.append("")

    # 模块 docstring 作为 callout
    if metadata["module_docstring"]:
        lines.append("> [!info] Module Purpose")
        for line in metadata["module_docstring"].split("\n"):
            lines.append(f"> {line}")
        lines.append("")

    # === Public API ===
    public_functions = [f for f in symbols["functions"] if not f["is_private"]]
    if public_functions:
        lines.append("## Public API")
        lines.append("")
        for func in public_functions:
            # 函数签名
            args_str = ", ".join(func["args"])
            signature = f'{func["name"]}({args_str})'
            if func["return_type"]:
                signature += f' -> {func["return_type"]}'

            lines.append(f"### `{signature}`")
            lines.append("")
            lines.append(f'**Location**: `{relative_path}:{func["lineno"]}` (hint)')

            if func["is_async"]:
                lines.append("**Type**: Async function")

            lines.append("")

            # Docstring
            if func["docstring"]:
                lines.append("> [!example] Documentation")
                for line in func["docstring"].split("\n"):
                    lines.append(f"> {line}")
                lines.append("")
            lines.append("")

    # === Classes ===
    if symbols["classes"]:
        lines.append("## Classes")
        lines.append("")
        for cls in symbols["classes"]:
            lines.append(f'### `{cls["name"]}`')
            lines.append("")
            lines.append(f'**Location**: `{relative_path}:{cls["lineno"]}` (hint)')

            # 基类
            if cls["bases"]:
                lines.append(f'**Inherits**: {", ".join(f"`{b}`" for b in cls["bases"])}')

            lines.append("")

            # Docstring
            if cls["docstring"]:
                lines.append("> [!info] Description")
                for line in cls["docstring"].split("\n"):
                    lines.append(f"> {line}")
                lines.append("")

            # 方法
            if cls["methods"]:
                public_methods = [m for m in cls["methods"] if not m["is_private"]]
                private_methods = [m for m in cls["methods"] if m["is_private"]]

                if public_methods:
                    lines.append("**Public Methods**:")
                    lines.append("")
                    for method in public_methods:
                        # 方法签名
                        args_str = ", ".join(method["args"])
                        method_sig = f'{method["name"]}({args_str})'
                        if method["return_type"]:
                            method_sig += f' -> {method["return_type"]}'

                        lines.append(f"#### `{method_sig}`")
                        lines.append("")
                        lines.append(
                            f'**Location**: `{relative_path}:{method["lineno"]}` (hint)'
                        )

                        if method["is_async"]:
                            lines.append("**Type**: Async method")

                        lines.append("")

                        # 方法 docstring
                        if method["docstring"]:
                            lines.append("> [!note] Method Documentation")
                            for line in method["docstring"].split("\n"):
                                lines.append(f"> {line}")
                            lines.append("")
                        lines.append("")

                if private_methods:
                    lines.append("<details>")
                    lines.append("<summary>Private methods</summary>")
                    lines.append("")
                    for method in private_methods:
                        args_str = ", ".join(method["args"])
                        method_sig = f'{method["name"]}({args_str})'
                        if method["return_type"]:
                            method_sig += f' -> {method["return_type"]}'
                        lines.append(
                            f'- `{method_sig}` — `{relative_path}:{method["lineno"]}`'
                        )
                    lines.append("")
                    lines.append("</details>")
                    lines.append("")

            lines.append("")

    # === Dependencies ===
    if dependencies["imports"]:
        lines.append("## Dependencies")
        lines.append("")

        # Internal（wikilinks）
        if dependencies["internal_imports"]:
            lines.append("**Internal**:")
            for imp in dependencies["internal_imports"]:
                link_name = imp.split(".")[-1]
                lines.append(f"- [[{link_name}]]")
            lines.append("")

        # External（行内代码）
        external = [
            imp
            for imp in dependencies["imports"]
            if not imp.startswith(f"{project_name}.")
        ]
        if external:
            lines.append("**External**:")
            for imp in external:
                lines.append(f"- `{imp}`")
            lines.append("")

    # === 页脚 ===
    lines.append("---")
    lines.append("")
    lines.append("**Navigation**: [[_PROJECT]] • [[_MODULES]]")

    return "\n".join(lines)
