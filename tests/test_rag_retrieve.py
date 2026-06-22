"""Tests for retrieval, RRF fusion, and graph boost (Phase 3: C2/C3/C4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain.rag.chunker import chunk_file
from brain.rag.index import RagIndex
from brain.rag.retrieve import (
    GRAPH_BOOST,
    apply_graph_boost,
    rrf_fuse,
    search,
)

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
