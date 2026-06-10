from __future__ import annotations

import subprocess

import pytest

from brain.git import GitError, find_repositories, repository_status


def init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    return path


def test_find_repositories_discovers_nested_repos(tmp_path):
    repo = init_repo(tmp_path / "workspace" / "project")

    assert find_repositories(tmp_path) == [repo.resolve()]


def test_repository_status_reports_changes(tmp_path):
    repo = init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("# Test\n", encoding="utf-8")

    status = repository_status(repo)

    assert status.path == repo.resolve()
    assert status.branch in {"main", "master"}
    assert status.changes == ("?? README.md",)


def test_find_repositories_rejects_missing_path(tmp_path):
    with pytest.raises(GitError, match="path does not exist"):
        find_repositories(tmp_path / "missing")
