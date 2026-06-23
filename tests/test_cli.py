"""Test CLI commands."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from code_nearby.cli import app

runner = CliRunner()


def test_status_shows_kb_path(tmp_path, monkeypatch):
    """Test status shows knowledge base path."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()

    def mock_get_kb_path():
        return vault_path

    monkeypatch.setattr("code_nearby.cli.config.get_kb_path", mock_get_kb_path)
    monkeypatch.setattr("code_nearby.tui.config.get_kb_path", mock_get_kb_path)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Knowledge base path:" in result.stdout
    assert str(vault_path) in result.stdout


def test_clear_config(tmp_path, monkeypatch):
    """Test clearing configuration."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("code_nearby.config.get_config_path", lambda: config_file)
    # Write a config so clear has something to delete
    config_file.write_text('{"local_path": "/custom/path"}')

    result = runner.invoke(app, ["clear"], input="y\n")

    assert result.exit_code == 0
    assert "Configuration cleared" in result.stdout
    assert not config_file.exists()


def test_analyze_runs_on_source_directory(tmp_path, monkeypatch):
    """Test analyze runs on a source directory (git not required)."""
    project = tmp_path / "project"
    project.mkdir()
    kb_path = tmp_path / "kb"
    kb_path.mkdir()

    def mock_get_kb_path():
        return kb_path

    monkeypatch.setattr("code_nearby.cli.config.get_kb_path", mock_get_kb_path)

    mock_result = {
        "success": True,
        "files_analyzed": 3,
        "added": 2,
        "modified": 1,
        "deleted": 0,
        "chunks_total": 10,
        "kb_path": "project",
        "error": None,
    }

    with patch("code_nearby.cli.run_full_analysis", return_value=mock_result):
        result = runner.invoke(app, ["analyze", str(project)])

    assert result.exit_code == 0
    assert "Analyzed 3 files" in result.stdout
    assert "10 RAG chunks indexed" in result.stdout
