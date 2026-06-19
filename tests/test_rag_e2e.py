"""End-to-end tests: assembly + CLI index/search (Phase 4: C6/C7/C8)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brain import cli, operations
from brain.rag.assemble import assemble, estimate_tokens
from brain.rag.chunker import chunk_file
from brain.rag.index import RagIndex
from brain.rag.retrieve import search

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
    payload = assemble("fetch remote url", search(index, "fetch remote url", k=3))
    assert payload["query"] == "fetch remote url"
    assert payload["results"]
    top = payload["results"][0]
    assert top["rank"] == 1
    assert top["ref"].startswith("repository.py:")
    # ref line must equal the chunk's start line (the "lines" range start)
    assert top["ref"].split(":")[1] == top["lines"].split("-")[0]
    assert top["type"] in {"function", "method", "class", "module"}
    assert "def fetch_remote" in top["content"]


def test_token_budget_trims_and_flags(index: RagIndex) -> None:
    results = search(index, "self root widget repository load", k=8)
    assert len(results) >= 2
    # budget that admits only the first chunk
    first_cost = estimate_tokens(results[0].chunk.content)
    payload = assemble("q", results, budget=first_cost)
    assert len(payload["results"]) == 1
    assert payload["truncated"] is True
    assert payload["token_estimate"] <= first_cost


def test_no_budget_keeps_all(index: RagIndex) -> None:
    results = search(index, "self", k=5)
    payload = assemble("q", results, budget=None)
    assert len(payload["results"]) == len(results)
    assert payload["truncated"] is False


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
    monkeypatch.setattr(
        operations.config, "load_config", lambda: {"local_path": str(kb), "git_repo": "x"}
    )
    # cli.operations and brain.storage both read config via the same module
    monkeypatch.chdir(repo)
    return repo


def test_cli_index_then_search_json(wired_project: Path) -> None:
    idx_result = runner.invoke(cli.app, ["index", "."])
    assert idx_result.exit_code == 0, idx_result.output
    assert "Indexed" in idx_result.output

    result = runner.invoke(cli.app, ["search", "verify token", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["results"][0]["qualified_name"] == "verify_token"
    assert payload["results"][0]["ref"] == "pkg/auth.py:4"
    assert "def verify_token" in payload["results"][0]["content"]


def test_cli_search_without_index_errors(wired_project: Path) -> None:
    result = runner.invoke(cli.app, ["search", "anything"])
    assert result.exit_code == 1
    assert "No search index" in result.output


def test_cli_search_human_output(wired_project: Path) -> None:
    runner.invoke(cli.app, ["index", "."])
    result = runner.invoke(cli.app, ["search", "verify_token"])
    assert result.exit_code == 0
    assert "pkg/auth.py:4" in result.output
    assert "verify_token" in result.output
