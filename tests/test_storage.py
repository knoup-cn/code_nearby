"""Test storage operations."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from brain import storage


def test_get_project_kb_path_github_https(tmp_path):
    """Test parsing GitHub HTTPS URL."""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"
    project_path.mkdir()

    with patch(
        "brain.git_utils.get_remote_url", return_value="https://github.com/octocat/hello-world.git"
    ):
        result = storage.get_project_kb_path(kb_path, project_path)

    assert result == kb_path / "octocat" / "hello-world"


def test_get_project_kb_path_github_ssh(tmp_path):
    """Test parsing GitHub SSH URL."""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"
    project_path.mkdir()

    with patch(
        "brain.git_utils.get_remote_url",
        return_value="git@github.com:octocat/hello-world.git",
    ):
        result = storage.get_project_kb_path(kb_path, project_path)

    assert result == kb_path / "octocat" / "hello-world"


def test_get_project_kb_path_gitlab(tmp_path):
    """Test parsing GitLab URL."""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"
    project_path.mkdir()

    with patch("brain.git_utils.get_remote_url", return_value="https://gitlab.com/myorg/myproject"):
        result = storage.get_project_kb_path(kb_path, project_path)

    assert result == kb_path / "myorg" / "myproject"


def test_get_project_kb_path_no_remote(tmp_path):
    """Test when repository has no remote."""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"
    project_path.mkdir()

    with patch("brain.git_utils.get_remote_url", return_value=None):
        result = storage.get_project_kb_path(kb_path, project_path)

    assert result is None


def test_ensure_project_kb_path_creates_directory(tmp_path):
    """Test that ensure_project_kb_path creates the directory structure."""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"
    project_path.mkdir()

    with patch("brain.git_utils.get_remote_url", return_value="https://github.com/test/repo.git"):
        result = storage.ensure_project_kb_path(kb_path, project_path)

    assert result.exists()
    assert result.is_dir()
    assert result == kb_path / "test" / "repo"


def test_ensure_project_kb_path_raises_on_no_remote(tmp_path):
    """Test that ensure_project_kb_path raises when remote is missing."""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"
    project_path.mkdir()

    with patch("brain.git_utils.get_remote_url", return_value=None):
        with pytest.raises(RuntimeError, match="Cannot determine repository identity"):
            storage.ensure_project_kb_path(kb_path, project_path)


def test_metadata_includes_kb_location(tmp_path):
    """Test that metadata records kb_location."""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"

    storage.save_project_metadata(kb_path, project_path, {"kb_location": "org/project"})

    metadata = storage.load_project_metadata(kb_path, project_path)
    assert metadata["kb_location"] == "org/project"
