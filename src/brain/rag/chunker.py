"""Tree-sitter chunking of source files into symbol-level chunks (G1).

Produces non-overlapping chunks per file:

- one ``module`` chunk: imports + module docstring + top-level constants
- one ``function`` chunk per module-level function (full source, incl. decorators)
- one ``class`` chunk per class (the class *preamble*: header + docstring +
  class-level attributes, i.e. everything before the first method)
- one ``method`` chunk per method (full source); nested classes recurse

Nested functions stay inside their enclosing function's chunk (never truncated).
Adding a language = register its suffix + parser in ``_parser`` and reuse the
same generic node walk; the chunk schema does not change (G3).
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

from tree_sitter import Language, Node, Parser

from brain.rag.schema import Chunk, base_chunk_id, compute_content_hash

# suffix -> tree-sitter language name
LANGUAGES_BY_SUFFIX: dict[str, str] = {".py": "python"}

_FUNC = "function_definition"
_CLASS = "class_definition"
_DECORATED = "decorated_definition"
_SYMBOL_WRAPPERS = (_FUNC, _CLASS, _DECORATED)


@cache
def _parser(language: str) -> Parser:
    """Return a cached parser for a language (bundled grammar, no download)."""
    if language == "python":
        import tree_sitter_python as ts_python

        return Parser(Language(ts_python.language()))
    raise ValueError(f"Unsupported language: {language}")


def detect_language(path: Path) -> str | None:
    """Map a file suffix to a supported language name, or None."""
    return LANGUAGES_BY_SUFFIX.get(path.suffix)


def chunk_file(file_path: Path, project_root: Path) -> list[Chunk]:
    """Chunk a single file into symbol-level :class:`Chunk` records.

    Unsupported languages, read errors, or empty files yield no chunks. A parse
    that produces no top-level symbols still yields the module chunk so the file
    remains retrievable.
    """
    language = detect_language(file_path)
    if language is None:
        return []

    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if not source.strip():
        return []

    rel_path = relative_path(file_path, project_root)
    src = source.encode("utf-8")
    root = _parser(language).parse(src).root_node

    imports = _collect_imports(src, root)
    builder = _ChunkBuilder(rel_path=rel_path, language=language, src=src, imports=imports)

    module_chunk = _module_chunk(src, root, builder)
    if module_chunk is not None:
        builder.add(module_chunk)

    _walk_scope(root, scope=[], parent_class=None, builder=builder)
    return builder.chunks


class _ChunkBuilder:
    """Accumulates chunks for one file and resolves chunk_id collisions."""

    def __init__(self, rel_path: str, language: str, src: bytes, imports: tuple[str, ...]):
        self.rel_path = rel_path
        self.language = language
        self.src = src
        self.imports = imports
        self.chunks: list[Chunk] = []
        self._seen_ids: set[str] = set()

    def make(
        self,
        *,
        chunk_type: str,
        symbol: str,
        qualified_name: str,
        parent_class: str | None,
        start_line: int,
        end_line: int,
        signature: str,
        docstring: str | None,
        content: str,
    ) -> Chunk:
        chunk_id = base_chunk_id(self.rel_path, qualified_name)
        if chunk_id in self._seen_ids:
            chunk_id = f"{chunk_id}:{start_line}"
        self._seen_ids.add(chunk_id)
        return Chunk(
            chunk_id=chunk_id,
            file_path=self.rel_path,
            language=self.language,
            chunk_type=chunk_type,
            symbol=symbol,
            qualified_name=qualified_name,
            parent_class=parent_class,
            start_line=start_line,
            end_line=end_line,
            imports=self.imports,
            signature=signature,
            docstring=docstring,
            content=content,
            content_hash=compute_content_hash(content),
        )

    def add(self, chunk: Chunk) -> None:
        self.chunks.append(chunk)


# --- traversal -------------------------------------------------------------

def _walk_scope(
    scope_node: Node, scope: list[str], parent_class: str | None, builder: _ChunkBuilder
) -> None:
    """Emit chunks for the function/class symbols directly inside scope_node."""
    body = scope_node.child_by_field_name("body") if scope_node.type == _CLASS else scope_node
    if body is None:
        return

    for child in body.named_children:
        if child.type not in _SYMBOL_WRAPPERS:
            continue
        span_node, inner = _unwrap(child)
        if inner is None:
            continue
        name = _name_of(inner, builder.src)
        if not name:
            continue
        qualified_name = ".".join([*scope, name])

        if inner.type == _FUNC:
            chunk_type = "method" if parent_class else "function"
            builder.add(
                builder.make(
                    chunk_type=chunk_type,
                    symbol=name,
                    qualified_name=qualified_name,
                    parent_class=parent_class,
                    start_line=span_node.start_point[0] + 1,
                    end_line=span_node.end_point[0] + 1,
                    signature=_signature(builder.src, span_node, inner),
                    docstring=_docstring(builder.src, inner),
                    content=_text(builder.src, span_node),
                )
            )
            # nested functions remain part of this function's content
        elif inner.type == _CLASS:
            preamble_end = _class_preamble_end(inner)
            start_line = span_node.start_point[0] + 1
            content = _slice(builder.src, span_node.start_byte, preamble_end)
            # end_line bounds the preamble content (methods are separate chunks)
            end_line = start_line + content.count("\n")
            builder.add(
                builder.make(
                    chunk_type="class",
                    symbol=name,
                    qualified_name=qualified_name,
                    parent_class=parent_class,
                    start_line=start_line,
                    end_line=end_line,
                    signature=_signature(builder.src, span_node, inner),
                    docstring=_docstring(builder.src, inner),
                    content=content,
                )
            )
            _walk_scope(inner, scope=[*scope, name], parent_class=name, builder=builder)


def _module_chunk(src: bytes, root: Node, builder: _ChunkBuilder) -> Chunk | None:
    """Build the module chunk from top-level non-symbol statements."""
    parts: list[str] = []
    first_line = 0
    last_line = 0
    for child in root.named_children:
        if child.type in _SYMBOL_WRAPPERS:
            continue
        parts.append(_text(src, child))
        if first_line == 0:
            first_line = child.start_point[0] + 1
        last_line = child.end_point[0] + 1

    if not parts:
        return None

    symbol = Path(builder.rel_path).stem
    return builder.make(
        chunk_type="module",
        symbol=symbol,
        qualified_name="",
        parent_class=None,
        start_line=first_line,
        end_line=last_line,
        signature=symbol,
        docstring=_module_docstring(src, root),
        content="\n".join(parts),
    )


# --- node helpers ----------------------------------------------------------

def _unwrap(child: Node) -> tuple[Node, Node | None]:
    """Return (span_node, inner_def). span_node includes decorators."""
    if child.type == _DECORATED:
        return child, child.child_by_field_name("definition")
    return child, child


def _name_of(node: Node, src: bytes) -> str:
    name_node = node.child_by_field_name("name")
    return _text(src, name_node) if name_node is not None else ""


def _signature(src: bytes, span_node: Node, inner: Node) -> str:
    """Decorators + def/class header up to the body, whitespace-collapsed."""
    body = inner.child_by_field_name("body")
    end = body.start_byte if body is not None else inner.end_byte
    header = _slice(src, span_node.start_byte, end)
    header = re.sub(r"\s+", " ", header).strip()
    return header.rstrip().removesuffix(":").rstrip() + ":" if header else header


def _class_preamble_end(class_node: Node) -> int:
    """Byte offset of the first method/nested class, or class end if none."""
    body = class_node.child_by_field_name("body")
    if body is None:
        return class_node.end_byte
    starts = [c.start_byte for c in body.named_children if c.type in _SYMBOL_WRAPPERS]
    return min(starts) if starts else class_node.end_byte


def _docstring(src: bytes, node: Node) -> str | None:
    body = node.child_by_field_name("body")
    return _first_string(src, body) if body is not None else None


def _module_docstring(src: bytes, root: Node) -> str | None:
    return _first_string(src, root)


def _first_string(src: bytes, block: Node) -> str | None:
    """Extract a leading docstring from a block/module's first statement."""
    for child in block.named_children:
        if child.type == "expression_statement" and child.named_child_count:
            inner = child.named_children[0]
            if inner.type == "string":
                return _clean_string(src, inner)
        break  # docstring must be the first statement
    return None


def _clean_string(src: bytes, string_node: Node) -> str:
    """Return docstring text without quotes/prefix, dedented and stripped."""
    for c in string_node.named_children:
        if c.type == "string_content":
            return _dedent(_text(src, c))
    # fallback: strip surrounding quotes
    raw = _text(src, string_node)
    raw = re.sub(r'^[a-zA-Z]*("""|\'\'\'|"|\')', "", raw)
    raw = re.sub(r'("""|\'\'\'|"|\')$', "", raw)
    return _dedent(raw)


def _dedent(text: str) -> str:
    import textwrap

    return textwrap.dedent(text).strip()


def _collect_imports(src: bytes, root: Node) -> tuple[str, ...]:
    """Collect module-level imported dotted names (best-effort, file-scoped)."""
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
                dotted = _text(src, module)
                if dotted:
                    names.append(dotted)
    # de-dup, preserve order
    seen: set[str] = set()
    ordered = [n for n in names if not (n in seen or seen.add(n))]
    return tuple(ordered)


def _dotted_name(src: bytes, node: Node) -> str:
    if node.type == "dotted_name":
        return _text(src, node)
    if node.type == "aliased_import":
        target = node.child_by_field_name("name")
        return _text(src, target) if target is not None else ""
    return ""


def _text(src: bytes, node: Node) -> str:
    return _slice(src, node.start_byte, node.end_byte)


def _slice(src: bytes, start: int, end: int) -> str:
    return src[start:end].decode("utf-8", errors="replace").rstrip()


def relative_path(file_path: Path, project_root: Path) -> str:
    """Repo-relative posix path for a file (falls back to the basename)."""
    try:
        return file_path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return file_path.name
