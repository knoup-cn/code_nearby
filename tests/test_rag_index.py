"""Tests for the FTS5 index + incremental orchestration (Phase 2: G4/G9)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from brain import operations
from brain.rag.chunker import chunk_file
from brain.rag.index import RagIndex

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_pkg"


@pytest.fixture
def index(tmp_path: Path) -> RagIndex:
    idx = RagIndex.open(tmp_path / "index.sqlite3")
    idx.upsert(chunk_file(FIXTURE_ROOT / "repository.py", FIXTURE_ROOT))
    yield idx
    idx.close()


def test_upsert_and_bm25(index: RagIndex) -> None:
    assert index.count() == 8
    assert index.query_bm25("fetch remote url", 5)[0] == "repository.py::fetch_remote"


def test_symbol_trigram_substring(index: RagIndex) -> None:
    # substring match across symbol + qualified name
    assert index.query_symbol("Repository", 5)[0] == "repository.py::Repository"
    assert index.query_symbol("load", 5) == ["repository.py::Repository.load"]


def test_metadata_filter(index: RagIndex) -> None:
    assert index.query_bm25("compute total", 5, language="python")
    assert index.query_bm25("compute total", 5, language="rust") == []
    assert index.query_bm25("compute total", 5, path_glob="repository.py")
    assert index.query_bm25("compute total", 5, path_glob="other/*.py") == []


def test_path_glob_double_star_matches_top_level(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    (root / "src" / "sub").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def alpha() -> int:\n    return 1\n")
    (root / "src" / "sub" / "b.py").write_text("def beta() -> int:\n    return 2\n")
    idx = RagIndex.open(tmp_path / "i.sqlite3")
    try:
        for rel in ("src/a.py", "src/sub/b.py"):
            idx.upsert(chunk_file(root / rel, root))
        # '**' must match both the nested file and the top-level one
        hits = idx.query_bm25("return", 10, path_glob="src/**/*.py")
        assert {cid.split("::")[0] for cid in hits} == {"src/a.py", "src/sub/b.py"}
    finally:
        idx.close()


def test_short_query_skips_trigram(index: RagIndex) -> None:
    assert index.query_symbol("ab", 5) == []  # < 3 chars


def test_get_chunks_preserves_order(index: RagIndex) -> None:
    ids = index.query_bm25("load widget", 5)
    chunks = index.get_chunks(ids)
    assert [c.chunk_id for c in chunks] == ids


def test_delete_file_removes_all_chunks(index: RagIndex) -> None:
    assert index.delete_file("repository.py") == 8
    assert index.count() == 0


def test_reupsert_is_idempotent(index: RagIndex) -> None:
    index.upsert(chunk_file(FIXTURE_ROOT / "repository.py", FIXTURE_ROOT))
    assert index.count() == 8  # no duplicate rows


def test_file_manifest_round_trip(index: RagIndex) -> None:
    manifest = index.file_manifest("repository.py")
    assert len(manifest) == 8
    chunks = chunk_file(FIXTURE_ROOT / "repository.py", FIXTURE_ROOT)
    assert manifest[chunks[0].chunk_id] == chunks[0].content_hash


# --- incremental orchestration (operations.index_project) ------------------

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _commit_repo(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real git repo + a knowledge base wired via monkeypatched config."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f1.py").write_text(
        '"""f1."""\n\n\ndef alpha():\n    return 1\n\n\ndef beta():\n    return 2\n'
    )
    (repo / "f2.py").write_text('"""f2."""\n\n\ndef gamma():\n    return 3\n')
    _commit_repo(repo)

    kb = tmp_path / "kb"
    kb.mkdir()
    monkeypatch.setattr(
        operations.config,
        "load_config",
        lambda: {"local_path": str(kb), "git_repo": "x"},
    )
    return repo


def test_index_project_full_then_incremental(project: Path) -> None:
    # full build
    result = operations.index_project(project, full_rebuild=True)
    assert result["success"]
    total = result["chunks_total"]
    assert total > 0
    assert result["chunks_added"] == total
    assert result["chunks_updated"] == 0

    # modify exactly one function body in f1 -> only that chunk re-indexed (G4)
    (project / "f1.py").write_text(
        '"""f1."""\n\n\ndef alpha():\n    return 99\n\n\ndef beta():\n    return 2\n'
    )
    _git(project, "commit", "-aqm", "edit alpha")
    inc = operations.index_project(project)
    assert inc["chunks_updated"] == 1
    assert inc["chunks_added"] == 0
    assert inc["chunks_deleted"] == 0
    assert inc["chunks_total"] == total  # net unchanged

    # add a new function -> one added, nothing updated
    (project / "f1.py").write_text(
        '"""f1."""\n\n\ndef alpha():\n    return 99\n\n\ndef beta():\n    return 2\n'
        "\n\ndef delta():\n    return 4\n"
    )
    _git(project, "commit", "-aqm", "add delta")
    inc2 = operations.index_project(project)
    assert inc2["chunks_added"] == 1
    assert inc2["chunks_updated"] == 0
    assert inc2["chunks_total"] == total + 1


def test_index_project_handles_deletion(project: Path) -> None:
    operations.index_project(project, full_rebuild=True)
    f2_chunks = len(chunk_file(project / "f2.py", project))
    assert f2_chunks > 0

    (project / "f2.py").unlink()
    _git(project, "commit", "-aqm", "remove f2")
    inc = operations.index_project(project)
    assert inc["chunks_deleted"] == f2_chunks


def test_full_rebuild_writes_gitignore(project: Path) -> None:
    operations.index_project(project, full_rebuild=True)
    gitignore = Path(operations.config.load_config()["local_path"]) / ".gitignore"
    assert "**/.rag/" in gitignore.read_text().split()
