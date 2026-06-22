"""Test git utility functions."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from brain import git_utils
from brain.git_utils import parse_repo_identity


def test_parse_repo_identity_github_https():
    """Test parsing GitHub HTTPS URL."""
    url = "https://github.com/octocat/hello-world.git"
    result = parse_repo_identity(url)
    assert result == ("octocat", "hello-world")


def test_parse_repo_identity_github_https_no_git_suffix():
    """Test parsing GitHub HTTPS URL without .git suffix."""
    url = "https://github.com/octocat/hello-world"
    result = parse_repo_identity(url)
    assert result == ("octocat", "hello-world")


def test_parse_repo_identity_github_ssh():
    """Test parsing GitHub SSH URL."""
    url = "git@github.com:octocat/hello-world.git"
    result = parse_repo_identity(url)
    assert result == ("octocat", "hello-world")


def test_parse_repo_identity_gitlab_https():
    """Test parsing GitLab HTTPS URL."""
    url = "https://gitlab.com/myorg/myproject.git"
    result = parse_repo_identity(url)
    assert result == ("myorg", "myproject")


def test_parse_repo_identity_gitlab_ssh():
    """Test parsing GitLab SSH URL."""
    url = "git@gitlab.com:myorg/myproject.git"
    result = parse_repo_identity(url)
    assert result == ("myorg", "myproject")


def test_parse_repo_identity_custom_host():
    """Test parsing custom Git host URL."""
    url = "https://git.company.com/team/project.git"
    result = parse_repo_identity(url)
    assert result == ("team", "project")


def test_parse_repo_identity_trailing_slash():
    """Test parsing URL with trailing slash."""
    url = "https://github.com/octocat/hello-world.git/"
    result = parse_repo_identity(url)
    assert result == ("octocat", "hello-world")


def test_parse_repo_identity_empty_string():
    """Test parsing empty string."""
    result = parse_repo_identity("")
    assert result is None


def test_parse_repo_identity_invalid_format():
    """Test parsing invalid URL format."""
    url = "not-a-valid-url"
    result = parse_repo_identity(url)
    assert result is None


def test_parse_repo_identity_single_segment():
    """Test parsing URL with single segment."""
    url = "https://github.com/onlyone"
    result = parse_repo_identity(url)
    assert result is None


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git repo with one committed file (README.md)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# readme\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def test_get_changed_files_detects_uncommitted_modification(git_repo: Path) -> None:
    """Incremental diff must catch edits to tracked files that aren't committed."""
    src = git_repo / "mod.py"
    src.write_text("a = 1\n")
    _git(git_repo, "add", "mod.py")
    _git(git_repo, "commit", "-m", "add mod")
    head = git_utils.require_current_commit(git_repo)

    # Modify a tracked file but do NOT commit.
    src.write_text("a = 2\n")

    changes = git_utils.get_changed_files(git_repo, head)
    assert src in changes["modified"]


def test_get_changed_files_includes_untracked(git_repo: Path) -> None:
    """Brand-new untracked files count as additions."""
    head = git_utils.require_current_commit(git_repo)
    new = git_repo / "new.py"
    new.write_text("x = 1\n")

    changes = git_utils.get_changed_files(git_repo, head)
    assert new in changes["added"]


def test_get_changed_files_detects_committed_deletion(git_repo: Path) -> None:
    """A committed deletion since the reference commit is reported."""
    src = git_repo / "gone.py"
    src.write_text("y = 1\n")
    _git(git_repo, "add", "gone.py")
    _git(git_repo, "commit", "-m", "add gone")
    head = git_utils.require_current_commit(git_repo)

    _git(git_repo, "rm", "gone.py")
    _git(git_repo, "commit", "-m", "rm gone")

    changes = git_utils.get_changed_files(git_repo, head)
    assert src in changes["deleted"]


def test_get_untracked_files_excludes_ignored(git_repo: Path) -> None:
    """get_untracked_files returns new files but honours .gitignore."""
    (git_repo / ".gitignore").write_text("ignored.py\n")
    (git_repo / "ignored.py").write_text("x = 1\n")
    (git_repo / "kept.py").write_text("y = 2\n")

    untracked = git_utils.get_untracked_files(git_repo)
    assert (git_repo / "kept.py") in untracked
    assert (git_repo / "ignored.py") not in untracked
