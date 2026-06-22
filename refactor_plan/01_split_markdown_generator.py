"""重构方案 1：拆分 Markdown 生成器

将 _generate_obsidian_md 拆分为职责单一的函数。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# ============================================================
# 新设计：模块化 Markdown 生成
# ============================================================


def generate_obsidian_md(
    file_path: Path,
    relative_path: Path,
    metadata: dict[str, Any],
    symbols: dict[str, list[dict[str, Any]]],
    dependencies: dict[str, list[str]],
    project_name: str,
) -> str:
    """生成 Obsidian 兼容的 Markdown（重构版）。

    将原来的 227 行巨型函数拆分为 6 个职责单一的函数。
    """
    module_name = relative_path.stem
    full_module_name = _build_full_module_name(relative_path)
    language = metadata["type"].split("-")[0] if "-" in metadata["type"] else "python"

    sections = [
        _generate_frontmatter(
            full_module_name, metadata, symbols, dependencies, relative_path, language
        ),
        "",  # 空行分隔
        _generate_header(module_name, metadata),
        "",
        _generate_public_api_section(symbols["functions"], relative_path),
        "",
        _generate_classes_section(symbols["classes"], relative_path),
        "",
        _generate_dependencies_section(dependencies, project_name),
        "",
        _generate_footer(),
    ]

    # 过滤掉空节（如无 public API 时）
    return "\n".join(s for s in sections if s)


# ============================================================
# 子函数：各司其职
# ============================================================


def _build_full_module_name(relative_path: Path) -> str:
    """构建完整模块名（如 brain.analyzer）。"""
    module_parts = []
    for part in relative_path.parts[:-1]:
        if part == "src":
            continue
        module_parts.append(part)
    module_parts.append(relative_path.stem)
    return ".".join(module_parts)


def _generate_frontmatter(
    full_module_name: str,
    metadata: dict[str, Any],
    symbols: dict[str, list[dict[str, Any]]],
    dependencies: dict[str, list[str]],
    relative_path: Path,
    language: str,
) -> str:
    """生成 YAML frontmatter（约 50 行）。"""
    lines = [
        "---",
        'brain_schema: "v1"',
        f'type: {metadata["type"]}',
        f'source_path: {metadata["path"]}',
        f"module: {full_module_name}",
    ]

    # Exports
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

    # Symbols（含 signature_hash）
    symbols_lines = _generate_symbols_metadata(symbols)
    if symbols_lines:
        lines.extend(symbols_lines)

    # Metrics
    lines.append(f'lines_of_code: {metadata["lines_of_code"]}')

    # Tags
    from brain.analyzer import _infer_tags
    tags = _infer_tags(relative_path, symbols, language)
    lines.append(f"tags: [{', '.join(tags)}]")

    lines.append("---")
    return "\n".join(lines)


def _generate_symbols_metadata(
    symbols: dict[str, list[dict[str, Any]]]
) -> list[str]:
    """生成 symbols 元数据列表。"""
    all_symbols = []
    for func in symbols["functions"]:
        all_symbols.append(func)
    for cls in symbols["classes"]:
        all_symbols.append(cls)

    if not all_symbols:
        return []

    lines = ["symbols:"]
    for sym in all_symbols:
        lines.append(f'  - name: {sym["name"]}')
        sym_type = "function" if "args" in sym else "class"
        lines.append(f"    type: {sym_type}")
        escaped_sig = sym["signature"].replace('"', '\\"')
        lines.append(f'    signature: "{escaped_sig}"')
        lines.append(f'    signature_hash: "{sym["signature_hash"]}"')
        lines.append(f'    location_hint: {sym["lineno"]}')
        lines.append(f'    is_private: {str(sym["is_private"]).lower()}')
        if sym_type == "function":
            lines.append(f'    is_async: {str(sym["is_async"]).lower()}')

    return lines


def _generate_header(module_name: str, metadata: dict[str, Any]) -> str:
    """生成标题和模块 docstring（约 10 行）。"""
    lines = [f"# {module_name}", ""]

    if metadata["module_docstring"]:
        lines.append("> [!info] Module Purpose")
        for line in metadata["module_docstring"].split("\n"):
            lines.append(f"> {line}")
        lines.append("")

    return "\n".join(lines)


def _generate_public_api_section(
    functions: list[dict[str, Any]], relative_path: Path
) -> str:
    """生成 Public API 节（约 30 行 per function）。"""
    public_functions = [f for f in functions if not f["is_private"]]
    if not public_functions:
        return ""

    lines = ["## Public API", ""]

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

    return "\n".join(lines)


def _generate_classes_section(
    classes: list[dict[str, Any]], relative_path: Path
) -> str:
    """生成 Classes 节（约 50 行 per class）。"""
    if not classes:
        return ""

    lines = ["## Classes", ""]

    for cls in classes:
        lines.extend(_generate_single_class(cls, relative_path))

    return "\n".join(lines)


def _generate_single_class(cls: dict[str, Any], relative_path: Path) -> list[str]:
    """生成单个类的文档。"""
    lines = [
        f'### `{cls["name"]}`',
        "",
        f'**Location**: `{relative_path}:{cls["lineno"]}` (hint)',
    ]

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
                lines.extend(_generate_single_method(method, relative_path))

        if private_methods:
            lines.extend(_generate_private_methods_details(private_methods, relative_path))

    lines.append("")
    return lines


def _generate_single_method(method: dict[str, Any], relative_path: Path) -> list[str]:
    """生成单个方法的文档。"""
    args_str = ", ".join(method["args"])
    method_sig = f'{method["name"]}({args_str})'
    if method["return_type"]:
        method_sig += f' -> {method["return_type"]}'

    lines = [
        f"#### `{method_sig}`",
        "",
        f'**Location**: `{relative_path}:{method["lineno"]}` (hint)',
    ]

    if method["is_async"]:
        lines.append("**Type**: Async method")

    lines.append("")

    if method["docstring"]:
        lines.append("> [!note] Method Documentation")
        for line in method["docstring"].split("\n"):
            lines.append(f"> {line}")
        lines.append("")

    lines.append("")
    return lines


def _generate_private_methods_details(
    private_methods: list[dict[str, Any]], relative_path: Path
) -> list[str]:
    """生成私有方法折叠区。"""
    lines = [
        "<details>",
        "<summary>Private methods</summary>",
        "",
    ]

    for method in private_methods:
        args_str = ", ".join(method["args"])
        method_sig = f'{method["name"]}({args_str})'
        if method["return_type"]:
            method_sig += f' -> {method["return_type"]}'
        lines.append(f'- `{method_sig}` — `{relative_path}:{method["lineno"]}`')

    lines.extend(["", "</details>", ""])
    return lines


def _generate_dependencies_section(
    dependencies: dict[str, list[str]], project_name: str
) -> str:
    """生成 Dependencies 节（约 20 行）。"""
    if not dependencies["imports"]:
        return ""

    lines = ["## Dependencies", ""]

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

    return "\n".join(lines)


def _generate_footer() -> str:
    """生成页脚导航。"""
    return "---\n\n**Navigation**: [[_PROJECT]] • [[_MODULES]]"


# ============================================================
# 迁移路径：旧函数委托给新实现
# ============================================================


def _generate_obsidian_md_legacy(
    file_path: Path,
    relative_path: Path,
    metadata: dict[str, Any],
    symbols: dict[str, list[dict[str, Any]]],
    dependencies: dict[str, list[str]],
    project_name: str,
) -> str:
    """旧版函数，委托给新实现（保持向后兼容）。

    迁移步骤：
    1. 部署阶段 1：新增新函数，旧函数调用新函数
    2. 部署阶段 2：测试通过后，删除旧函数，重命名新函数
    """
    return generate_obsidian_md(
        file_path, relative_path, metadata, symbols, dependencies, project_name
    )
