"""Tests for the tree-sitter chunker (Phase 1: G1/G2/G3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain.rag.chunker import chunk_file, detect_language
from brain.rag.schema import Chunk, compute_content_hash

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_pkg"
FIXTURE_FILE = FIXTURE_ROOT / "repository.py"


@pytest.fixture(scope="module")
def chunks() -> list[Chunk]:
    return chunk_file(FIXTURE_FILE, FIXTURE_ROOT)


def _by_symbol(chunks: list[Chunk], symbol: str) -> Chunk:
    return next(c for c in chunks if c.symbol == symbol)


def test_detect_language() -> None:
    assert detect_language(Path("a.py")) == "python"
    assert detect_language(Path("a.rs")) is None


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
    spans = sorted(
        (c.start_line, c.end_line) for c in chunks if c.chunk_type != "module"
    )
    for (_, prev_end), (next_start, _) in zip(spans, spans[1:], strict=False):
        assert next_start > prev_end


def test_chunk_ids_unique_and_hashes_stable(chunks: list[Chunk]) -> None:
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    fn = _by_symbol(chunks, "compute_total")
    assert fn.content_hash == compute_content_hash(fn.content)


def test_unsupported_language_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "main.rs"
    f.write_text("fn main() {}")
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
