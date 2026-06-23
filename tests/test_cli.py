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

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Knowledge base path:" in result.stdout
    assert str(vault_path) in result.stdout


def test_analyze_runs_on_source_directory(tmp_path, monkeypatch):
    """Test analyze runs on a source directory."""
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


def test_default_shows_help():
    """Test default (no subcommand) shows guidance."""
    result = runner.invoke(app)
    assert result.exit_code == 0
    assert "MCP server" in result.stdout
