"""Tests for the tree-sitter chunker (Phase 1: G1/G2/G3)."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from code_nearby.rag.chunker import chunk_file, detect_language
from code_nearby.rag.schema import Chunk, compute_content_hash

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_pkg"
FIXTURE_FILE = FIXTURE_ROOT / "repository.py"


@pytest.fixture(scope="module")
def chunks() -> list[Chunk]:
    return chunk_file(FIXTURE_FILE, FIXTURE_ROOT)


def _by_symbol(chunks: list[Chunk], symbol: str) -> Chunk:
    return next(c for c in chunks if c.symbol == symbol)


def test_detect_language() -> None:
    """验证后缀到语言名的映射。"""
    assert detect_language(Path("a.py")) == "python"
    assert detect_language(Path("a.rs")) == "rust"
    assert detect_language(Path("a.go")) == "go"
    assert detect_language(Path("a.js")) == "javascript"
    assert detect_language(Path("a.ts")) == "typescript"
    assert detect_language(Path("a.java")) == "java"
    assert detect_language(Path("a.cpp")) is None  # 不支持的语言


def test_module_chunk_holds_imports_and_docstring(chunks: list[Chunk]) -> None:
    module = next(c for c in chunks if c.chunk_type == "module")
    assert module.imports == ("os", "pathlib")
    assert "Sample module" in (module.docstring or "")
    # module chunk carries top-level constant, not symbol bodies
    assert "MAX_RETRIES = 3" in module.content
    assert "def compute_total" not in module.content


def test_function_body_not_truncated(chunks: list[Chunk]) -> None:
    # the nested function must remain inside the enclosing function chunk
    fn = _by_symbol(chunks, "compute_total")
    assert fn.chunk_type == "function"
    assert "def doubled" in fn.content
    assert fn.content.rstrip().endswith("for v in values)")


def test_decorator_in_signature(chunks: list[Chunk]) -> None:
    fn = _by_symbol(chunks, "compute_total")
    assert fn.signature.startswith("@cache")
    assert fn.start_line == 15  # span starts at the decorator line


def test_async_in_signature(chunks: list[Chunk]) -> None:
    fn = _by_symbol(chunks, "fetch_remote")
    assert fn.signature.startswith("async def fetch_remote")


def test_class_preamble_excludes_methods(chunks: list[Chunk]) -> None:
    cls = _by_symbol(chunks, "Repository")
    assert cls.chunk_type == "class"
    assert cls.signature == "class Repository(Base):"
    assert 'kind = "widget"' in cls.content
    assert "def __init__" not in cls.content  # methods are separate chunks


def test_methods_carry_parent_class(chunks: list[Chunk]) -> None:
    methods = [c for c in chunks if c.chunk_type == "method"]
    assert {m.symbol for m in methods} == {"__init__", "name", "load", "_private_helper"}
    assert all(m.parent_class == "Repository" for m in methods)
    load = _by_symbol(chunks, "load")
    assert load.qualified_name == "Repository.load"
    assert load.signature.startswith("async def load")


def test_chunks_do_not_overlap(chunks: list[Chunk]) -> None:
    # non-module chunks partition the file without overlapping line spans
    spans = sorted((c.start_line, c.end_line) for c in chunks if c.chunk_type != "module")
    for (_, prev_end), (next_start, _) in itertools.pairwise(spans):
        assert next_start > prev_end


def test_chunk_ids_unique_and_hashes_stable(chunks: list[Chunk]) -> None:
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    fn = _by_symbol(chunks, "compute_total")
    assert fn.content_hash == compute_content_hash(fn.content)


def test_unsupported_language_returns_empty(tmp_path: Path) -> None:
    """不支持的后缀（如 .cpp）应返回空列表。"""
    f = tmp_path / "Main.cpp"
    f.write_text("class Main {};")
    assert chunk_file(f, tmp_path) == []


def test_empty_file_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "blank.py"
    f.write_text("\n  \n")
    assert chunk_file(f, tmp_path) == []


def test_syntax_error_is_tolerated(tmp_path: Path) -> None:
    # tree-sitter is error-tolerant: a broken file still yields what it can
    f = tmp_path / "broken.py"
    f.write_text("def ok():\n    return 1\n\ndef broken(:\n    pass\n")
    result = chunk_file(f, tmp_path)
    assert any(c.symbol == "ok" for c in result)


# ======================================================================
# 多语言 chunking 测试
# ======================================================================

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_chunk_go_file() -> None:
    """验证 Go 文件能正常分块（基础支持）。"""
    go_file = FIXTURES_DIR / "go_pkg" / "sample.go"
    chunks = chunk_file(go_file, go_file.parent)

    assert len(chunks) > 0
    # 应包含 module chunk
    assert any(c.chunk_type == "module" for c in chunks)
    # ComputeTotal 函数
    assert any(c.symbol == "ComputeTotal" for c in chunks)
    # NewRepository 函数
    assert any(c.symbol == "NewRepository" for c in chunks)
    # 所有 chunk language 字段应为 "go"
    assert all(c.language == "go" for c in chunks)
    # TODO: type_declaration → type_spec 嵌套及 method 归属待后续 PR 深度支持


def test_chunk_javascript_file() -> None:
    """验证 JavaScript 文件能正常分块。"""
    js_file = FIXTURES_DIR / "js_pkg" / "sample.js"
    chunks = chunk_file(js_file, js_file.parent)

    assert len(chunks) > 0
    assert any(c.chunk_type == "module" for c in chunks)
    assert any(c.symbol == "computeTotal" for c in chunks)
    assert any(c.symbol == "fetchRemote" for c in chunks)
    assert any(c.symbol == "Repository" and c.chunk_type == "class" for c in chunks)
    assert all(c.language == "javascript" for c in chunks)


def test_chunk_typescript_file() -> None:
    """验证 TypeScript 文件能正常分块。"""
    ts_file = FIXTURES_DIR / "ts_pkg" / "sample.ts"
    chunks = chunk_file(ts_file, ts_file.parent)

    assert len(chunks) > 0
    assert any(c.chunk_type == "module" for c in chunks)
    assert any(c.symbol == "computeTotal" for c in chunks)
    assert any(c.symbol == "Repository" and c.chunk_type == "class" for c in chunks)
    assert all(c.language == "typescript" for c in chunks)


def test_chunk_rust_file() -> None:
    """验证 Rust 文件能正常分块（基础支持）。"""
    rs_file = FIXTURES_DIR / "rust_pkg" / "sample.rs"
    chunks = chunk_file(rs_file, rs_file.parent)

    assert len(chunks) > 0
    assert any(c.chunk_type == "module" for c in chunks)
    assert any(c.symbol == "compute_total" for c in chunks)
    assert all(c.language == "rust" for c in chunks)
    # TODO: struct_item 内方法提取及 impl_item 关联待后续 PR 深度支持


def test_multi_language_detection() -> None:
    """验证各种后缀的语言检测。"""
    assert detect_language(Path("main.go")) == "go"
    assert detect_language(Path("app.js")) == "javascript"
    assert detect_language(Path("app.jsx")) == "javascript"
    assert detect_language(Path("app.ts")) == "typescript"
    assert detect_language(Path("main.rs")) == "rust"
    assert detect_language(Path("Main.java")) == "java"
    assert detect_language(Path("script.rb")) is None


def test_chunk_java_file() -> None:
    """验证 Java 文件能正常分块。"""
    java_file = FIXTURES_DIR / "java_pkg" / "Repository.java"
    chunks = chunk_file(java_file, java_file.parent)

    assert len(chunks) > 0
    assert any(c.chunk_type == "module" for c in chunks)
    # load 方法
    assert any(c.symbol == "load" for c in chunks)
    # Repository 类
    assert any(c.symbol == "Repository" and c.chunk_type == "class" for c in chunks)
    # 所有 chunk language 字段应为 "java"
    assert all(c.language == "java" for c in chunks)

# ======================================================================
# 物理分解测试
# ======================================================================


def test_large_function_decomposes_into_blocks(tmp_path: Path) -> None:
    """超过 MAX_FUNCTION_LINES 的函数应分解为 sub-chunk。"""
    lines = ["def big():\n", '    """Doc."""\n']
    # 生成 ~250 行的函数体（超过 MAX_FUNCTION_LINES=200）
    for i in range(120):
        lines.append(f"    x{i} = {i}\n")
    lines.append("    if True:\n")
    for i in range(120, 240):
        lines.append(f"        y{i} = {i}\n")
    lines.append("    return None\n")

    f = tmp_path / "bigfunc.py"
    f.write_text("".join(lines))
    chunks = chunk_file(f, tmp_path)

    # sub-chunk 的 chunk_id 包含 :blk/ 后缀
    sub_chunks = [c for c in chunks if c.chunk_type == "function"]
    assert len(sub_chunks) >= 2, f"got {len(sub_chunks)} sub-chunks"
    for sc in sub_chunks:
        assert ":blk/" in sc.chunk_id
        assert "[in big()]" in sc.content
        assert "def big():" in sc.content  # 上下文签名头

    # 所有 sub-chunk 不应有重叠行
    spans = sorted((c.start_line, c.end_line) for c in sub_chunks)
    for (_, prev_end), (next_start, _) in itertools.pairwise(spans):
        assert next_start > prev_end, f"blocks overlap: {spans}"


def test_small_function_stays_intact(tmp_path: Path) -> None:
    """小函数不应被分解。"""
    src = """def small() -> int:
    '''A small function.'''
    x = 1
    y = 2
    return x + y
"""
    f = tmp_path / "small.py"
    f.write_text(src)
    chunks = chunk_file(f, tmp_path)

    func_chunks = [c for c in chunks if c.chunk_type == "function"]
    assert len(func_chunks) == 1
    assert ":blk/" not in func_chunks[0].chunk_id
    assert "return x + y" in func_chunks[0].content


def test_decomposition_preserves_function_identity(tmp_path: Path) -> None:
    """分解后 sub-chunk 的 qualified_name 应为父函数名。"""
    lines = ["def handler(req):\n", '    """Handle request."""\n']
    for i in range(120):
        lines.append(f"    step{i} = {i}\n")
    lines.append("    if req.auth:\n")
    for i in range(120, 240):
        lines.append(f"        process({i})\n")
    lines.append("    return req\n")

    f = tmp_path / "handler.py"
    f.write_text("".join(lines))
    chunks = chunk_file(f, tmp_path)

    sub_chunks = [c for c in chunks if c.chunk_type == "function"]
    assert len(sub_chunks) >= 2, f"got {len(sub_chunks)} sub-chunks"
    for sc in sub_chunks:
        assert sc.qualified_name == "handler"
        assert sc.symbol.startswith("handler:blk/")
        assert "[in handler()]" in sc.content
