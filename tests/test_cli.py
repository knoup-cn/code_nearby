from __future__ import annotations

from brain.cli import main


def test_repos_command_prints_repository_path(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)

    exit_code = main(["repos", str(tmp_path)])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == str(repo.resolve())
