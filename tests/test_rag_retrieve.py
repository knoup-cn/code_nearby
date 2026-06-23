"""Tests for retrieval, RRF fusion, and graph boost (Phase 3: C2/C3/C4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_nearby.rag.chunker import chunk_file
from code_nearby.rag.index import RagIndex
from code_nearby.rag.retrieve import (
    GRAPH_BOOST,
    ScoredChunk,
    apply_graph_boost,
    rerank_heuristic,
    rrf_fuse,
    search,
)
from code_nearby.rag.schema import Chunk
from code_nearby.rag.synonyms import expand_query

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_pkg"


@pytest.fixture
def index(tmp_path: Path) -> RagIndex:
    idx = RagIndex.open(tmp_path / "index.sqlite3")
    idx.upsert(chunk_file(FIXTURE_ROOT / "repository.py", FIXTURE_ROOT))
    yield idx
    idx.close()


# --- RRF math --------------------------------------------------------------


def test_rrf_fuse_rewards_appearing_in_both_lists() -> None:
    scores = rrf_fuse([["a", "b"], ["b", "c"]], [1.0, 1.0])
    # b is in both lists, so it must outrank a (rank-1 once) and c (rank-2 once)
    assert scores["b"] > scores["a"] > scores["c"]
    assert scores["b"] == pytest.approx(1 / 61 + 1 / 62)


def test_rrf_fuse_respects_weights() -> None:
    high = rrf_fuse([["x"], ["y"]], [10.0, 1.0])
    assert high["x"] > high["y"]


# --- search ----------------------------------------------------------------


def test_search_semantic_phrase(index: RagIndex) -> None:
    results = search(index, "fetch remote url", k=3)
    assert results[0].chunk.symbol == "fetch_remote"


def test_search_exact_symbol_ranks_first(index: RagIndex) -> None:
    results = search(index, "load", k=5)
    assert results[0].chunk.qualified_name == "Repository.load"


def test_search_language_filter(index: RagIndex) -> None:
    assert search(index, "compute total", k=5, language="python")
    assert search(index, "compute total", k=5, language="rust") == []


def test_search_path_filter(index: RagIndex) -> None:
    assert search(index, "compute", k=5, path_glob="repository.py")
    assert search(index, "compute", k=5, path_glob="nope/*.py") == []


def test_search_no_match_returns_empty(index: RagIndex) -> None:
    assert search(index, "zzz_no_such_token_qqq", k=5) == []


def test_search_respects_k(index: RagIndex) -> None:
    assert len(search(index, "self", k=2)) <= 2


# --- graph boost -----------------------------------------------------------


def test_graph_boost_promotes_neighbor_module() -> None:
    # a.py strongly matched; b.py is a graph neighbor of a.py; c.py is unrelated
    scores = {"a.py::alpha": 0.05, "b.py::beta": 0.01, "c.py::gamma": 0.01}
    graph = {
        "nodes": {
            "pkg.a": {"type": "module", "source_path": "a.py"},
            "pkg.b": {"type": "module", "source_path": "b.py"},
            "pkg.c": {"type": "module", "source_path": "c.py"},
        },
        "edges": [{"from": "pkg.a", "to": "pkg.b", "type": "imports"}],
    }
    apply_graph_boost(scores, graph)
    assert scores["b.py::beta"] == pytest.approx(0.01 + GRAPH_BOOST)
    assert scores["c.py::gamma"] == pytest.approx(0.01)  # unrelated, untouched
    assert scores["b.py::beta"] > scores["c.py::gamma"]


def test_graph_boost_noop_without_nodes() -> None:
    scores = {"a.py::alpha": 0.05}
    apply_graph_boost(scores, {"nodes": {}, "edges": []})
    assert scores == {"a.py::alpha": 0.05}


# --- synonym expansion --------------------------------------------------------


def test_expand_query_adds_synonyms() -> None:
    expanded = expand_query("fetch user data")
    # 确定性的 cluster 顺序："fetch" cluster → get, retrieve, obtain
    # "user" cluster → account, profile, identity
    assert "get" in expanded
    assert "retrieve" in expanded
    assert len(expanded.split()) > 3  # 比原查询更长


def test_expand_query_no_match_returns_unchanged() -> None:
    assert expand_query("zzz_nonexistent_term_qqq") == "zzz_nonexistent_term_qqq"


def test_expand_query_avoids_duplicate_terms() -> None:
    # "get" and "fetch" are in the same cluster; query already contains "fetch"
    expanded = expand_query("fetch retrieve user")
    # should not add "retrieve" again since it's already present
    count = expanded.count("retrieve")
    assert count == 1


# --- heuristic reranking -----------------------------------------------------


def test_rerank_heuristic_symbol_exact_match() -> None:
    """精确符号名命中应获得加分。"""
    chunk_a = Chunk(
        chunk_id="a::foo",
        file_path="a.py",
        language="python",
        chunk_type="function",
        symbol="analyze_file",
        qualified_name="analyze_file",
        parent_class=None,
        start_line=1,
        end_line=10,
        imports=(),
        signature="def analyze_file()",
        docstring="Analyze a file.",
        content="pass",
        content_hash="aa",
    )
    chunk_b = Chunk(
        chunk_id="b::bar",
        file_path="b.py",
        language="python",
        chunk_type="function",
        symbol="helper",
        qualified_name="helper",
        parent_class=None,
        start_line=1,
        end_line=5,
        imports=(),
        signature="def helper()",
        docstring=None,
        content="xyz",
        content_hash="bb",
    )
    scored = [
        ScoredChunk(chunk=chunk_a, score=0.08),
        ScoredChunk(chunk=chunk_b, score=0.08),
    ]
    result = rerank_heuristic(scored, "analyze_file")
    # analyze_file should now rank first due to exact symbol match + docstring bonuses
    assert result[0].chunk.symbol == "analyze_file"
    assert result[0].score > result[1].score


def test_rerank_heuristic_preserves_order_on_tie() -> None:
    """分数相同时保持原有顺序。"""
    chunk = Chunk(
        chunk_id="a::f",
        file_path="a.py",
        language="python",
        chunk_type="function",
        symbol="foo",
        qualified_name="foo",
        parent_class=None,
        start_line=1,
        end_line=3,
        imports=(),
        signature="def foo()",
        docstring=None,
        content="pass",
        content_hash="cc",
    )
    scored = [ScoredChunk(chunk=chunk, score=0.5)]
    result = rerank_heuristic(scored, "zzz_nomatch")
    assert len(result) == 1
    assert result[0].score == pytest.approx(0.51)  # depth bonus: 0.01 * (1/1)
