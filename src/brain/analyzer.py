"""Code analysis operations."""

from __future__ import annotations

import ast
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def analyze_file(file_path: Path, kb_path: Path, project_root: Path) -> None:
    """Analyze a single file and write to knowledge base.

    Args:
        file_path: File to analyze
        kb_path: Knowledge base root path
        project_root: Project root for relative path calculation
    """
    # Only Python files for now
    if file_path.suffix != ".py":
        return

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        # Skip unparseable files
        return

    # Extract structure
    relative_path = file_path.relative_to(project_root)
    project_name = project_root.resolve().name  # Use absolute path to get actual name
    metadata = _extract_metadata(file_path, relative_path, tree, source)
    symbols = _extract_symbols(tree, source)
    dependencies = _extract_dependencies(tree, project_name)

    # Generate Obsidian-friendly markdown
    content = _generate_obsidian_md(
        file_path=file_path,
        relative_path=relative_path,
        metadata=metadata,
        symbols=symbols,
        dependencies=dependencies,
        project_name=project_name,
    )

    # Write to knowledge base
    kb_file = kb_path / relative_path.with_suffix(".md")
    kb_file.parent.mkdir(parents=True, exist_ok=True)
    kb_file.write_text(content, encoding="utf-8")


def _extract_metadata(
    file_path: Path, relative_path: Path, tree: ast.AST, source: str
) -> dict[str, Any]:
    """Extract file-level metadata."""
    module_docstring = ast.get_docstring(tree)

    # Count lines (excluding blank lines and comments)
    lines = source.split("\n")
    code_lines = [
        line for line in lines if line.strip() and not line.strip().startswith("#")
    ]

    return {
        "type": "python-module",
        "path": str(relative_path),
        "module_docstring": module_docstring,
        "lines_of_code": len(code_lines),
        "last_analyzed": datetime.now(UTC).isoformat(),
    }


def _extract_symbols(tree: ast.AST, source: str) -> dict[str, list[dict[str, Any]]]:
    """Extract functions and classes from top-level only.

    Args:
        tree: AST tree
        source: Source code (for extracting signature lines)

    Returns:
        Dictionary with 'functions' and 'classes' lists
    """
    symbols: dict[str, list[dict[str, Any]]] = {"functions": [], "classes": []}
    lines = source.split("\n")

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Extract arguments with type hints
            args = []
            for arg in node.args.args:
                arg_str = arg.arg
                if arg.annotation:
                    arg_str += f": {ast.unparse(arg.annotation)}"
                args.append(arg_str)

            # Extract return type
            return_type = None
            if node.returns:
                return_type = ast.unparse(node.returns)

            # Extract signature from source
            signature = _extract_signature(lines, node.lineno, node.end_lineno)
            signature_hash = _compute_signature_hash(signature)

            symbols["functions"].append(
                {
                    "name": node.name,
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                    "docstring": ast.get_docstring(node),
                    "args": args,
                    "return_type": return_type,
                    "is_private": node.name.startswith("_"),
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "signature": signature,
                    "signature_hash": signature_hash,
                }
            )
        elif isinstance(node, ast.ClassDef):
            # Extract methods with full details
            methods = []
            for n in ast.iter_child_nodes(node):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Extract arguments with type hints
                    args = []
                    for arg in n.args.args:
                        arg_str = arg.arg
                        if arg.annotation:
                            arg_str += f": {ast.unparse(arg.annotation)}"
                        args.append(arg_str)

                    # Extract return type
                    return_type = None
                    if n.returns:
                        return_type = ast.unparse(n.returns)

                    # Extract method signature from source
                    method_signature = _extract_signature(lines, n.lineno, n.end_lineno)
                    method_signature_hash = _compute_signature_hash(method_signature)

                    methods.append({
                        "name": n.name,
                        "lineno": n.lineno,
                        "end_lineno": n.end_lineno,
                        "docstring": ast.get_docstring(n),
                        "args": args,
                        "return_type": return_type,
                        "is_private": n.name.startswith("_"),
                        "is_async": isinstance(n, ast.AsyncFunctionDef),
                        "signature": method_signature,
                        "signature_hash": method_signature_hash,
                    })

            # Extract base classes
            bases = [ast.unparse(base) for base in node.bases]

            # Extract signature from source
            signature = _extract_signature(lines, node.lineno, node.end_lineno)
            signature_hash = _compute_signature_hash(signature)

            symbols["classes"].append(
                {
                    "name": node.name,
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                    "docstring": ast.get_docstring(node),
                    "methods": methods,
                    "bases": bases,
                    "is_private": node.name.startswith("_"),
                    "signature": signature,
                    "signature_hash": signature_hash,
                }
            )

    return symbols


def _extract_signature(lines: list[str], start_line: int, end_line: int) -> str:
    """Extract function/class signature from source.

    Args:
        lines: Source code lines
        start_line: Starting line number (1-indexed)
        end_line: Ending line number (1-indexed)

    Returns:
        Signature string (e.g., "def analyze_file(...):")
    """
    # Extract the def/class line (may span multiple lines)
    signature_lines = []
    for i in range(start_line - 1, min(end_line, len(lines))):
        line = lines[i].strip()
        signature_lines.append(line)
        # Stop at the first line ending with ":"
        if line.endswith(":"):
            break

    return " ".join(signature_lines)


def _compute_signature_hash(signature: str) -> str:
    """Compute SHA256 hash of signature (first 8 chars).

    Args:
        signature: Function/class signature

    Returns:
        8-character hex hash
    """
    normalized = signature.strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:8]


def _extract_dependencies(tree: ast.AST, project_name: str) -> dict[str, list[str]]:
    """Extract imports and dependencies.

    Args:
        tree: AST tree of the module
        project_name: Name of the project (for detecting internal imports)

    Returns:
        Dictionary with 'imports' and 'internal_imports' lists
    """
    imports: list[str] = []
    internal_imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                # Check if import starts with project name (e.g., "brain.*", "myproject.*")
                if alias.name.startswith(f"{project_name}."):
                    internal_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_name = node.module
                imports.append(module_name)
                # Track internal imports (project.* or from project import ...)
                if module_name.startswith(f"{project_name}.") or module_name == project_name:
                    # For "from project import x, y", expand to project.x, project.y
                    if module_name == project_name:
                        for alias in node.names:
                            internal_imports.append(f"{project_name}.{alias.name}")
                    else:
                        internal_imports.append(module_name)

    return {
        "imports": sorted(set(imports)),
        "internal_imports": sorted(set(internal_imports)),
    }


def _infer_tags(relative_path: Path, symbols: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Automatically infer tags from file content."""
    tags = ["python"]

    # Based on path
    parts = relative_path.parts
    if "tests" in parts or "test" in parts:
        tags.append("test")
    if "operations" in relative_path.stem:
        tags.append("core")
    if "cli" in relative_path.stem:
        tags.append("cli")
    if "tui" in relative_path.stem:
        tags.append("tui")

    # Based on content
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
    """Generate Obsidian-friendly Markdown with frontmatter and wikilinks.

    Args:
        file_path: Absolute path to the source file
        relative_path: Path relative to project root
        metadata: File metadata
        symbols: Extracted symbols (functions, classes)
        dependencies: Import dependencies
        project_name: Name of the project (for filtering internal imports)
    """
    module_name = relative_path.stem

    # Build full module name (e.g., "brain.analyzer")
    module_parts = []
    for part in relative_path.parts[:-1]:  # Exclude filename
        if part == "src":
            continue
        module_parts.append(part)
    module_parts.append(module_name)
    full_module_name = ".".join(module_parts)

    lines: list[str] = []

    # === Frontmatter (YAML) ===
    lines.append("---")
    lines.append('brain_schema: "v1"')
    lines.append(f'type: {metadata["type"]}')
    lines.append(f'source_path: {metadata["path"]}')
    lines.append(f'module: {full_module_name}')

    # Exports (public API)
    exports = [f["name"] for f in symbols["functions"] if not f["is_private"]]
    exports += [c["name"] for c in symbols["classes"] if not c["is_private"]]
    if exports:
        lines.append("exports:")
        for exp in exports:
            lines.append(f"  - {exp}")

    # Dependencies (only internal wikilinks)
    if dependencies["internal_imports"]:
        lines.append("dependencies:")
        for imp in dependencies["internal_imports"]:
            link_name = imp.split(".")[-1]
            lines.append(f'  - "[[{link_name}]]"')

    # Symbols (with signature_hash and location_hint)
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
            lines.append(f'    type: {sym_type}')
            # Escape signature for YAML (replace " with \")
            escaped_sig = sym["signature"].replace('"', '\\"')
            lines.append(f'    signature: "{escaped_sig}"')
            lines.append(f'    signature_hash: "{sym["signature_hash"]}"')
            lines.append(f'    location_hint: {sym["lineno"]}')
            lines.append(f'    is_private: {str(sym["is_private"]).lower()}')
            if sym_type == "function":
                lines.append(f'    is_async: {str(sym["is_async"]).lower()}')

    # Metrics
    lines.append(f'lines_of_code: {metadata["lines_of_code"]}')
    lines.append(f'last_analyzed: {metadata["last_analyzed"]}')

    # Tags
    tags = _infer_tags(relative_path, symbols)
    lines.append(f'tags: [{", ".join(tags)}]')

    lines.append("---")
    lines.append("")

    # === Header ===
    lines.append(f"# {module_name}")
    lines.append("")

    # Module docstring as callout
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
            # Function signature
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

            # Base classes
            if cls["bases"]:
                lines.append(f'**Inherits**: {", ".join(f"`{b}`" for b in cls["bases"])}')

            lines.append("")

            # Docstring
            if cls["docstring"]:
                lines.append("> [!info] Description")
                for line in cls["docstring"].split("\n"):
                    lines.append(f"> {line}")
                lines.append("")

            # Methods
            if cls["methods"]:
                public_methods = [m for m in cls["methods"] if not m["is_private"]]
                private_methods = [m for m in cls["methods"] if m["is_private"]]

                if public_methods:
                    lines.append("**Public Methods**:")
                    lines.append("")
                    for method in public_methods:
                        # Method signature
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

                        # Method docstring
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
                        lines.append(f'- `{method_sig}` — `{relative_path}:{method["lineno"]}`')
                    lines.append("")
                    lines.append("</details>")
                    lines.append("")

            lines.append("")

    # === Dependencies ===
    if dependencies["imports"]:
        lines.append("## Dependencies")
        lines.append("")

        # Internal (wikilinks)
        if dependencies["internal_imports"]:
            lines.append("**Internal**:")
            for imp in dependencies["internal_imports"]:
                link_name = imp.split(".")[-1]
                lines.append(f"- [[{link_name}]]")
            lines.append("")

        # External (code blocks)
        external = [
            imp for imp in dependencies["imports"]
            if not imp.startswith(f"{project_name}.")
        ]
        if external:
            lines.append("**External**:")
            for imp in external:
                lines.append(f"- `{imp}`")
            lines.append("")

    # === Footer ===
    lines.append("---")
    lines.append("")
    lines.append("**Navigation**: [[_PROJECT]] • [[_MODULES]]")

    return "\n".join(lines)
