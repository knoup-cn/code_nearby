"""End-to-end tests: assembly + CLI index/search (Phase 4: C6/C7/C8)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from code_nearby import cli, config
from code_nearby.rag.assemble import assemble, chunk_tokens
from code_nearby.rag.chunker import chunk_file
from code_nearby.rag.index import RagIndex
from code_nearby.rag.retrieve import ScoredChunk, search

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_pkg"
runner = CliRunner()


# --- assembly --------------------------------------------------------------


@pytest.fixture
def index(tmp_path: Path) -> RagIndex:
    idx = RagIndex.open(tmp_path / "index.sqlite3")
    idx.upsert(chunk_file(FIXTURE_ROOT / "repository.py", FIXTURE_ROOT))
    yield idx
    idx.close()


def test_payload_shape_and_citation(index: RagIndex) -> None:
    payload = assemble(
        "fetch remote url",
        search(index, "fetch remote url", k=3),
        project_root=FIXTURE_ROOT,
    )
    assert payload["query"] == "fetch remote url"
    assert payload["results"]
    top = payload["results"][0]
    assert top["rank"] == 1
    assert top["ref"].startswith("repository.py:")
    # ref 指向原始 chunk 起始行，lines 显示窗口扩展后的实际范围
    assert top["type"] in {"function", "method", "class", "module"}
    assert "def fetch_remote" in top["content"]
    assert "context_window" in top


def test_token_budget_trims_and_flags(index: RagIndex) -> None:
    results = search(index, "self root widget repository load", k=8)
    assert len(results) >= 2
    # budget that admits only the first chunk (using actual content from disk)
    first_chunk = results[0].chunk
    from code_nearby.rag.source_fetch import fetch_source

    snippet = fetch_source(
        FIXTURE_ROOT,
        first_chunk.file_path,
        first_chunk.start_line,
        first_chunk.end_line,
    )
    assert snippet is not None
    first_cost = chunk_tokens(first_chunk, content=snippet.content)
    payload = assemble(
        "q",
        results,
        budget=first_cost,
        project_root=FIXTURE_ROOT,
        window_strategy="none",
    )
    assert len(payload["results"]) == 1
    assert payload["truncated"] is True
    assert payload["token_estimate"] <= first_cost


def test_no_budget_keeps_all(index: RagIndex) -> None:
    results = search(index, "self", k=5)
    payload = assemble("q", results, budget=None, project_root=FIXTURE_ROOT)
    assert len(payload["results"]) == len(results)
    assert payload["truncated"] is False


def test_budget_keeps_smaller_lower_ranked_chunk() -> None:
    chunks = sorted(
        chunk_file(FIXTURE_ROOT / "repository.py", FIXTURE_ROOT),
        key=chunk_tokens,
    )
    small1, small2, big = chunks[0], chunks[1], chunks[-1]
    assert chunk_tokens(big) > chunk_tokens(small2)  # precondition: big won't fit the slack
    # rank order places the oversized chunk between two small ones
    results = [
        ScoredChunk(small1, 3.0),
        ScoredChunk(big, 2.0),
        ScoredChunk(small2, 1.0),
    ]
    payload = assemble("q", results, budget=chunk_tokens(small1) + chunk_tokens(small2))
    kept = {r["ref"] for r in payload["results"]}
    assert f"{small1.file_path}:{small1.start_line}" in kept
    assert f"{small2.file_path}:{small2.start_line}" in kept  # filled despite the earlier big chunk
    assert f"{big.file_path}:{big.start_line}" not in kept
    assert payload["truncated"] is True


# --- CLI end-to-end --------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def wired_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "auth.py").write_text(
        '"""Auth module."""\n\n\n'
        "def verify_token(token: str) -> bool:\n"
        '    """Verify a user token."""\n'
        "    return bool(token)\n"
    )
    _git(repo, "init", "-q")
    _git(repo, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    kb = tmp_path / "kb"
    kb.mkdir()
    monkeypatch.setattr(config, "load_config", lambda: {"local_path": str(kb)})
    # cli.operations and code_nearby.storage both read config via the same module
    monkeypatch.chdir(repo)
    return repo


def test_cli_analyze_then_search_json(wired_project: Path) -> None:
    result = runner.invoke(cli.app, ["analyze", "."])
    assert result.exit_code == 0, result.output
    assert "Analyzed" in result.output

    result = runner.invoke(cli.app, ["search", "verify token", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["results"][0]["qualified_name"] == "verify_token"
    # ref 指向原始 chunk 起始行
    assert payload["results"][0]["ref"].startswith("pkg/auth.py:")
    assert "def verify_token" in payload["results"][0]["content"]


def test_cli_search_without_index_errors(wired_project: Path) -> None:
    result = runner.invoke(cli.app, ["search", "anything"])
    assert result.exit_code == 1
    assert "No search index" in result.output


def test_cli_search_human_output(wired_project: Path) -> None:
    runner.invoke(cli.app, ["analyze", "."])
    result = runner.invoke(cli.app, ["search", "verify_token"])
    assert result.exit_code == 0
    assert "pkg/auth.py:4" in result.output
    assert "verify_token" in result.output
