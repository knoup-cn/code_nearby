"""Test CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from brain.cli import app
from brain.config import load_config, save_config, validate_config
from brain.operations.config import needs_overwrite

runner = CliRunner()


def test_status_not_initialized(tmp_path, monkeypatch):
    """Test status when not initialized."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("brain.config.get_config_path", lambda: config_file)

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "Not initialized" in result.stdout


def test_validate_config():
    """Test configuration validation."""
    # Empty config is valid (uninitialized)
    assert validate_config({})

    # Both fields present is valid
    assert validate_config({"git_repo": "url", "local_path": "/path"})

    # Only git_repo is invalid
    assert not validate_config({"git_repo": "url"})

    # Only local_path is invalid
    assert not validate_config({"local_path": "/path"})


def test_save_invalid_config_raises(tmp_path, monkeypatch):
    """Test saving invalid config raises error."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("brain.config.get_config_path", lambda: config_file)

    with pytest.raises(ValueError, match="git_repo and local_path must both exist"):
        save_config({"git_repo": "url"})


def test_init_git_mode(tmp_path, monkeypatch):
    """Test initialization with git repository."""
    config_file = tmp_path / "config.json"
    vault_path = tmp_path / "vault"
    monkeypatch.setattr("brain.config.get_config_path", lambda: config_file)

    def mock_clone(repo_url: str, target_path: Path, overwrite: bool = False) -> tuple[bool, str]:
        target_path.mkdir(parents=True, exist_ok=True)
        assert overwrite is False
        return True, "Cloned"

    with patch("brain.git_utils.test_git_connection", return_value=(True, "Connected")):
        with patch("brain.git_utils.clone_repo", side_effect=mock_clone):
            result = runner.invoke(
                app, ["init"], input=f"{vault_path}\nhttps://github.com/test/repo.git\n"
            )

    assert result.exit_code == 0
    cfg = load_config()
    assert cfg["git_repo"] == "https://github.com/test/repo.git"
    assert cfg["local_path"] == str(vault_path.resolve())


def test_status_shows_config(tmp_path, monkeypatch):
    """Test status command shows configuration."""
    config_file = tmp_path / "config.json"
    vault_path = tmp_path / "vault"
    monkeypatch.setattr("brain.config.get_config_path", lambda: config_file)

    def mock_clone(repo_url: str, target_path: Path, overwrite: bool = False) -> tuple[bool, str]:
        target_path.mkdir(parents=True, exist_ok=True)
        assert overwrite is False
        return True, "Cloned"

    with patch("brain.git_utils.test_git_connection", return_value=(True, "Connected")):
        with patch("brain.git_utils.clone_repo", side_effect=mock_clone):
            runner.invoke(app, ["init"], input=f"{vault_path}\nhttps://github.com/test/repo.git\n")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Knowledge base Git repo:" in result.stdout
    assert "Knowledge base local path:" in result.stdout


def test_clear_config(tmp_path, monkeypatch):
    """Test clearing configuration."""
    config_file = tmp_path / "config.json"
    vault_path = tmp_path / "vault"
    monkeypatch.setattr("brain.config.get_config_path", lambda: config_file)

    def mock_clone(repo_url: str, target_path: Path, overwrite: bool = False) -> tuple[bool, str]:
        target_path.mkdir(parents=True, exist_ok=True)
        assert overwrite is False
        return True, "Cloned"

    with patch("brain.git_utils.test_git_connection", return_value=(True, "Connected")):
        with patch("brain.git_utils.clone_repo", side_effect=mock_clone):
            runner.invoke(app, ["init"], input=f"{vault_path}\nhttps://github.com/test/repo.git\n")

    result = runner.invoke(app, ["clear"], input="y\n")

    assert result.exit_code == 0
    assert "Cleared" in result.stdout
    assert not config_file.exists()


def test_needs_overwrite(tmp_path):
    """Test overwrite detection for init."""
    target = tmp_path / "vault"
    assert not needs_overwrite(target)

    target.mkdir()
    assert not needs_overwrite(target)

    (target / "file.md").write_text("x")
    assert needs_overwrite(target)
