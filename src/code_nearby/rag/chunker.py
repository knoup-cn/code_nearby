"""Tree-sitter 源码分块——将源文件切分为符号级 Chunk 记录。

每种语言注册后缀 + parser 即可复用同一套节点遍历逻辑；chunk schema 不变。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node

from code_nearby.lang_config import LanguageConfig, detect_language, get_config
from code_nearby.rag.schema import Chunk, base_chunk_id, compute_content_hash
from code_nearby.tree_sitter_utils import (
    StatementBlock,
    collect_imports,
    decompose_function_body,
    extract_signature,
    get_docstring,
    get_module_docstring,
    get_parser,
    node_slice,
    node_text,
    relative_path,
    walk_symbols,
)

# 函数超过此行数则触发物理分解
MAX_FUNCTION_LINES = 200


def chunk_file(file_path: Path, project_root: Path) -> list[Chunk]:
    """将单个文件切分为符号级 :class:`Chunk` 记录。

    不支持的语言、读取错误或空文件返回空列表。
    无法解析出顶层符号的也会产出 module chunk，保证文件可检索。
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

    cfg = get_config(language)
    rel_path = relative_path(file_path, project_root)
    src = source.encode("utf-8")
    root = get_parser(language).parse(src).root_node

    imports = collect_imports(src, root, language)
    builder = _ChunkBuilder(rel_path=rel_path, language=language, src=src, imports=imports)

    module_c = _module_chunk(src, root, builder, cfg)
    if module_c is not None:
        builder.add(module_c)

    # 共享 CST 遍历：一次产出所有符号（含递归进入类体的方法）
    for info in walk_symbols(root, src, cfg):
        if info.kind in ("function", "method"):
            qname = ".".join([*info.scope, info.name]) if info.scope else info.name
            sig = extract_signature(
                builder.source_lines, info.span_node, info.inner_node
            )
            line_count = info.end_line - info.start_line + 1

            if line_count > MAX_FUNCTION_LINES:
                # 超大函数：物理分解为 StatementBlock 子块
                body_node = info.inner_node.child_by_field_name("body")
                if body_node is not None:
                    blocks = decompose_function_body(body_node)
                    if blocks:
                        for blk in blocks:
                            sub = _make_sub_chunk(
                                builder, info, qname, sig, blk, len(blocks)
                            )
                            builder.add(sub)
                        continue  # 不再创建完整函数 chunk

            parent_cls = (
                info.scope[-1] if info.scope and info.kind == "method" else None
            )
            builder.add(
                builder.make(
                    chunk_type=info.kind,
                    symbol=info.name,
                    qualified_name=qname,
                    parent_class=parent_cls,
                    start_line=info.start_line,
                    end_line=info.end_line,
                    signature=sig,
                    docstring=get_docstring(src, info.inner_node),
                    content=node_text(src, info.span_node),
                )
            )
        elif info.kind == "class":
            qname = ".".join([*info.scope, info.name]) if info.scope else info.name
            preamble_end = _class_preamble_end(info.inner_node, cfg)
            preamble_text = node_slice(src, info.span_node.start_byte, preamble_end)
            builder.add(
                builder.make(
                    chunk_type="class",
                    symbol=info.name,
                    qualified_name=qname,
                    parent_class=info.scope[-1] if info.scope else None,
                    start_line=info.start_line,
                    end_line=info.start_line + preamble_text.count("\n"),
                    signature=extract_signature(
                        builder.source_lines, info.span_node, info.inner_node
                    ),
                    docstring=get_docstring(src, info.inner_node),
                    content=preamble_text,
                )
            )

    return builder.chunks


class _ChunkBuilder:
    """累积一个文件的所有 chunk，处理 chunk_id 冲突。"""

    def __init__(self, rel_path: str, language: str, src: bytes, imports: tuple[str, ...]):
        self.rel_path = rel_path
        self.language = language
        self.src = src
        self.source_lines = src.decode("utf-8", errors="replace").split("\n")
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


def _module_chunk(
    src: bytes, root: Node, builder: _ChunkBuilder, cfg: LanguageConfig
) -> Chunk | None:
    """从顶层非符号语句构建 module chunk。"""
    # 构建需要排除的符号类型集合
    func_types = {cfg.func_type}
    if cfg.method_func_types:
        func_types.update(cfg.method_func_types)
    exclude_types = func_types | set(cfg.class_types) | set(cfg.wrapper_types)
    if cfg.decorated_type:
        exclude_types.add(cfg.decorated_type)

    parts: list[str] = []
    first_line = 0
    last_line = 0
    for child in root.named_children:
        if child.type in exclude_types:
            continue
        parts.append(node_text(src, child))
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
        docstring=get_module_docstring(src, root),
        content="\n".join(parts),
    )


# ======================================================================
# Chunker 专用 helper（不放入 tree_sitter_utils）
# ======================================================================


def _make_sub_chunk(
    builder: _ChunkBuilder,
    info: object,
    qualified_name: str,
    signature: str,
    block: StatementBlock,
    total: int,
) -> Chunk:
    """从 :class:`StatementBlock` 构建子块 Chunk。"""
    from code_nearby.tree_sitter_utils import SymbolInfo

    assert isinstance(info, SymbolInfo)

    chunk_id = base_chunk_id(builder.rel_path, qualified_name)
    chunk_id = f"{chunk_id}:blk/{block.index}"
    if chunk_id in builder._seen_ids:
        chunk_id = f"{chunk_id}:{block.start_line}"
    builder._seen_ids.add(chunk_id)

    # 上下文头：告知 LLM 此块属于哪个函数
    header = f"[in {qualified_name}()]\n{signature}\n"
    header += (
        f"# --- block {block.index + 1}/{total}: "
        f"{block.label} (L{block.start_line}-L{block.end_line}) ---"
    )
    body_parts = [node_text(builder.src, n) for n in block.nodes]
    content = header + "\n" + "\n".join(body_parts)

    parent_cls = (
        info.scope[-1] if info.scope and info.kind == "method" else None
    )
    return Chunk(
        chunk_id=chunk_id,
        file_path=builder.rel_path,
        language=builder.language,
        chunk_type=info.kind,
        symbol=f"{info.name}:blk/{block.index}",
        qualified_name=qualified_name,
        parent_class=parent_cls,
        start_line=block.start_line,
        end_line=block.end_line,
        imports=builder.imports,
        signature=signature,
        docstring=None,
        content=content,
        content_hash=compute_content_hash(content),
    )


def _class_preamble_end(class_node: Node, cfg: LanguageConfig) -> int:
    """类体中第一个方法/嵌套类的字节偏移，无则返回类结束位置。"""
    body = class_node.child_by_field_name("body")
    if body is None:
        return class_node.end_byte

    # 方法/嵌套类节点类型集合
    method_types = set(cfg.method_func_types) if cfg.method_func_types else {cfg.func_type}
    wrapper_types = method_types | set(cfg.class_types) | set(cfg.wrapper_types)
    if cfg.decorated_type:
        wrapper_types.add(cfg.decorated_type)

    starts = [c.start_byte for c in body.named_children if c.type in wrapper_types]
    return min(starts) if starts else class_node.end_byte
