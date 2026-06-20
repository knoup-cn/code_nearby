"""Test git utility functions."""
from __future__ import annotations

import subprocess
from unittest.mock import patch

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


def test_clone_repo_clones_directly_to_target_path(tmp_path):
    """Test that clone_repo uses the configured local path as clone target."""
    from brain.git_utils import clone_repo

    target_path = tmp_path / "vault"
    repo_url = "https://github.com/octocat/hello-world.git"

    completed = subprocess.CompletedProcess(
        args=["git", "clone", repo_url, str(target_path)],
        returncode=0,
        stdout="",
        stderr="",
    )

    with patch("brain.git_utils.subprocess.run", return_value=completed) as run:
        success, message = clone_repo(repo_url, target_path)

    assert success
    assert message == "Cloned"
    run.assert_called_once_with(
        ["git", "clone", repo_url, str(target_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
