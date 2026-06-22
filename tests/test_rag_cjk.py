"""Tests for CJK bigram indexing and querying in FTS5."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain.rag.chunker import chunk_file
from brain.rag.index import (
    RagIndex,
    _cjk_bigrams,
    _is_cjk,
    _search_blob,
    _terms,
)

# --- _is_cjk -----------------------------------------------------------


def test_is_cjk_basic() -> None:
    assert _is_cjk("中")
    assert _is_cjk("文")
    assert _is_cjk("あ") is False  # hiragana
    assert _is_cjk("a") is False
    assert _is_cjk("1") is False


# --- _cjk_bigrams ------------------------------------------------------


def test_cjk_bigrams_pure_chinese() -> None:
    assert _cjk_bigrams("获取用户数据") == ["获取", "取用", "用户", "户数", "数据"]


def test_cjk_bigrams_single_char() -> None:
    assert _cjk_bigrams("获") == ["获"]


def test_cjk_bigrams_two_chars() -> None:
    assert _cjk_bigrams("数据") == ["数据"]


def test_cjk_bigrams_mixed() -> None:
    result = _cjk_bigrams("使用 fetch_data 获取远程数据")
    # "使用" → ["使用"], "获取远程数据" → ["获取", "取远", "远程", "程数", "数据"]
    assert "使用" in result
    assert "获取" in result
    assert "取远" in result
    assert "远程" in result
    assert "程数" in result
    assert "数据" in result
    assert "fetch" not in result
    assert "data" not in result


def test_cjk_bigrams_no_cjk() -> None:
    assert _cjk_bigrams("hello world") == []
    assert _cjk_bigrams("def get_user():") == []
    assert _cjk_bigrams("") == []


def test_cjk_bigrams_multiple_segments() -> None:
    """中断的非 CJK 字符应重置缓冲区。"""
    result = _cjk_bigrams("中文 hello 世界")
    assert result == ["中文", "世界"]


# --- _terms (query-side CJK) -------------------------------------------


def test_terms_chinese_query() -> None:
    terms = _terms("获取用户")
    assert "获取" in terms
    assert "取用" in terms
    assert "用户" in terms


def test_terms_mixed_query() -> None:
    terms = _terms("fetch 用户数据")
    assert "fetch" in terms
    assert "用户" in terms
    assert "户数" in terms
    assert "数据" in terms


def test_terms_no_cjk() -> None:
    terms = _terms("fetch_remote_url")
    assert "fetch" in terms
    assert "remote" in terms
    assert "url" in terms


def test_terms_case_insensitive() -> None:
    """中文没有大小写概念，但应与英文逻辑一致。"""
    terms = _terms("GetUser 用户")
    assert "getuser" in terms or "get" in terms
    assert "用户" in terms


# --- _search_blob (index-side CJK) -------------------------------------


def test_search_blob_includes_cjk_bigrams() -> None:
    """索引 blob 应包含从 docstring + content 提取的 CJK bigram。"""
    from brain.rag.schema import Chunk

    chunk = Chunk(
        chunk_id="test.py::get_user",
        file_path="test.py",
        language="python",
        chunk_type="function",
        symbol="get_user",
        qualified_name="get_user",
        parent_class="",
        start_line=1,
        end_line=5,
        imports=[],
        signature="def get_user():",
        docstring="获取用户数据",
        content='"""获取用户数据"""\ndef get_user():\n    return None\n',
        content_hash="abc123",
    )
    blob = _search_blob(chunk)
    assert "get_user" in blob
    assert "获取" in blob
    assert "取用" in blob
    assert "用户" in blob
    assert "户数" in blob
    assert "数据" in blob


def test_search_blob_no_cjk() -> None:
    """纯英文 chunk 不产生 CJK bigram（回归测试）。"""
    from brain.rag.schema import Chunk

    chunk = Chunk(
        chunk_id="test.py::add",
        file_path="test.py",
        language="python",
        chunk_type="function",
        symbol="add",
        qualified_name="add",
        parent_class="",
        start_line=1,
        end_line=3,
        imports=[],
        signature="def add(a, b):",
        docstring="Add two numbers.",
        content="def add(a, b):\n    return a + b\n",
        content_hash="def456",
    )
    blob = _search_blob(chunk)
    assert "add" in blob
    assert "numbers" in blob
    # No CJK content → no CJK bigrams in blob (no false positives)
    # The blob should still contain base content
    assert "return" in blob


# --- End-to-end: index Chinese content → query in Chinese ---------------


@pytest.fixture
def cjk_index(tmp_path: Path) -> RagIndex:
    """Create a temporary .py file with Chinese docstrings, chunk it, index it."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "chinese_code.py").write_text(
        '# -*- coding: utf-8 -*-\n'
        '"""用户管理模块。"""\n\n'
        'def get_user(user_id: int) -> dict:\n'
        '    """根据用户ID获取用户数据。"""\n'
        '    return {"id": user_id}\n\n'
        'def delete_user(user_id: int) -> None:\n'
        '    """删除指定用户。"""\n'
        '    pass\n\n'
        'def fetch_remote_config(url: str) -> dict:\n'
        '    """从远程URL获取配置信息。"""\n'
        '    return {}\n',
        encoding="utf-8",
    )
    idx = RagIndex.open(tmp_path / "index.sqlite3")
    idx.upsert(chunk_file(src / "chinese_code.py", src))
    yield idx
    idx.close()


def test_end_to_end_chinese_search_hits(cjk_index: RagIndex) -> None:
    """中文查询应当命中包含中文 docstring 的 chunk。"""
    assert cjk_index.count() > 0

    # 搜索"用户数据" → 应命中 get_user（docstring: "获取用户数据"）
    hits = cjk_index.query_bm25("用户数据", 10)
    assert hits, "Chinese query should return results"
    assert any("get_user" in h for h in hits), (
        f"get_user should be in results, got {hits}"
    )


def test_end_to_end_chinese_partial_match(cjk_index: RagIndex) -> None:
    """部分中文词也应命中（bigram 的召回特性）。"""
    hits = cjk_index.query_bm25("获取", 10)
    assert hits, "'获取' should hit chunks with '获取用户数据' docstring"
    assert any("get_user" in h for h in hits)


def test_end_to_end_chinese_miss(cjk_index: RagIndex) -> None:
    """不相关的中文查询不应命中。"""
    hits = cjk_index.query_bm25("支付退款", 10)
    assert not hits


def test_end_to_end_mixed_query(cjk_index: RagIndex) -> None:
    """混合中英文查询：英文命中代码，中文命中 docstring。"""
    hits = cjk_index.query_bm25("fetch 配置", 10)
    assert hits, "Mixed query should hit"
    # Should match fetch_remote_config (has "fetch" + "配置" in docstring)
    matched_ids = [h for h in hits if "fetch_remote_config" in h]
    assert matched_ids, f"fetch_remote_config should match, got {hits}"


def test_end_to_end_english_still_works(cjk_index: RagIndex) -> None:
    """回归：纯英文查询功能不受影响。"""
    hits = cjk_index.query_bm25("delete user", 10)
    assert hits, "English query should still work"
    assert any("delete_user" in h for h in hits)
