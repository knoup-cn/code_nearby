"""Obsidian Markdown 文档生成器。"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def generate_obsidian_md(
    file_path: Path,
    relative_path: Path,
    metadata: dict[str, Any],
    symbols: dict[str, list[dict[str, Any]]],
    dependencies: dict[str, list[str]],
    project_name: str,
) -> str:
    """生成 Obsidian 兼容的 Markdown。

    Args:
        file_path: 源文件绝对路径
        relative_path: 相对于项目根目录的路径
        metadata: 文件元数据
        symbols: 提取的符号（函数、类）
        dependencies: import 依赖
        project_name: 项目名称（用于过滤内部 import）

    Returns:
        完整的 Markdown 文档字符串
    """
    module_name = relative_path.stem
    full_module_name = _build_full_module_name(relative_path, module_name)

    sections = [
        _generate_frontmatter(
            full_module_name, relative_path, metadata, symbols, dependencies, project_name
        ),
        _generate_header(module_name, metadata),
        _generate_public_api(symbols["functions"], relative_path),
        _generate_classes(symbols["classes"], relative_path),
        _generate_dependencies(dependencies, project_name),
        _generate_footer(),
    ]

    return "\n\n".join(s for s in sections if s)


def _build_full_module_name(relative_path: Path, module_name: str) -> str:
    """构建完整模块名（如 brain.analyzer）。"""
    module_parts = []
    for part in relative_path.parts[:-1]:  # 排除文件名
        if part == "src":
            continue
        module_parts.append(part)
    module_parts.append(module_name)
    return ".".join(module_parts)


def _generate_frontmatter(
    full_module_name: str,
    relative_path: Path,
    metadata: dict[str, Any],
    symbols: dict[str, list[dict[str, Any]]],
    dependencies: dict[str, list[str]],
    project_name: str,
) -> str:
    """生成 YAML frontmatter。"""
    lines = [
        "---",
        'brain_schema: "v1"',
        f'type: {metadata["type"]}',
        f'source_path: {metadata["path"]}',
        f"module: {full_module_name}",
    ]

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
    all_symbols = symbols["functions"] + symbols["classes"]
    if all_symbols:
        lines.append("symbols:")
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

    # Metrics
    lines.append(f'lines_of_code: {metadata["lines_of_code"]}')

    # Tags
    language = metadata["type"].split("-")[0] if "-" in metadata["type"] else "python"
    tags = _infer_tags(relative_path, symbols, language)
    lines.append(f"tags: [{', '.join(tags)}]")

    lines.append("---")
    return "\n".join(lines)


def _generate_header(module_name: str, metadata: dict[str, Any]) -> str:
    """生成标题和模块描述。"""
    lines = [f"# {module_name}", ""]

    if metadata["module_docstring"]:
        lines.append("> [!info] Module Purpose")
        for line in metadata["module_docstring"].split("\n"):
            lines.append(f"> {line}")

    return "\n".join(lines) if lines else ""


def _generate_public_api(functions: list[dict[str, Any]], relative_path: Path) -> str:
    """生成 Public API 章节。"""
    public_functions = [f for f in functions if not f["is_private"]]
    if not public_functions:
        return ""

    lines = ["## Public API", ""]

    for func in public_functions:
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

        if func["docstring"]:
            lines.append("> [!example] Documentation")
            for line in func["docstring"].split("\n"):
                lines.append(f"> {line}")
            lines.append("")

    return "\n".join(lines)


def _generate_classes(classes: list[dict[str, Any]], relative_path: Path) -> str:
    """生成 Classes 章节。"""
    if not classes:
        return ""

    lines = ["## Classes", ""]

    for cls in classes:
        lines.append(f'### `{cls["name"]}`')
        lines.append("")
        lines.append(f'**Location**: `{relative_path}:{cls["lineno"]}` (hint)')

        if cls["bases"]:
            lines.append(f'**Inherits**: {", ".join(f"`{b}`" for b in cls["bases"])}')

        lines.append("")

        if cls["docstring"]:
            lines.append("> [!info] Description")
            for line in cls["docstring"].split("\n"):
                lines.append(f"> {line}")
            lines.append("")

        if cls["methods"]:
            public_methods = [m for m in cls["methods"] if not m["is_private"]]
            private_methods = [m for m in cls["methods"] if m["is_private"]]

            if public_methods:
                lines.append("**Public Methods**:")
                lines.append("")
                for method in public_methods:
                    args_str = ", ".join(method["args"])
                    method_sig = f'{method["name"]}({args_str})'
                    if method["return_type"]:
                        method_sig += f' -> {method["return_type"]}'

                    lines.append(f"#### `{method_sig}`")
                    lines.append("")
                    lines.append(f'**Location**: `{relative_path}:{method["lineno"]}` (hint)')

                    if method["is_async"]:
                        lines.append("**Type**: Async method")

                    lines.append("")

                    if method["docstring"]:
                        lines.append("> [!note] Method Documentation")
                        for line in method["docstring"].split("\n"):
                            lines.append(f"> {line}")
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
                    lines.append(f'- `{method_sig}` — `{relative_path}:{method["lineno"]}`')
                lines.append("")
                lines.append("</details>")

        lines.append("")

    return "\n".join(lines)


def _generate_dependencies(dependencies: dict[str, list[str]], project_name: str) -> str:
    """生成 Dependencies 章节。"""
    if not dependencies["imports"]:
        return ""

    lines = ["## Dependencies", ""]

    if dependencies["internal_imports"]:
        lines.append("**Internal**:")
        for imp in dependencies["internal_imports"]:
            link_name = imp.split(".")[-1]
            lines.append(f"- [[{link_name}]]")
        lines.append("")

    external = [
        imp for imp in dependencies["imports"] if not imp.startswith(f"{project_name}.")
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


def _infer_tags(
    relative_path: Path, symbols: dict[str, list[dict[str, Any]]], language: str
) -> list[str]:
    """根据文件内容和路径自动推断标签。"""
    from brain.lang_config import get_config

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
