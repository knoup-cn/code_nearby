"""Git repository operations."""

from __future__ import annotations

import subprocess
from pathlib import Path


def is_git_repo(path: Path) -> bool:
    """Check if path is a Git repository."""
    return (path / ".git").exists()


def get_current_commit(repo_path: Path) -> str | None:
    """Get current HEAD commit hash."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_changed_files(repo_path: Path, since_commit: str | None = None) -> dict[str, list[Path]]:
    """Get changed files since last commit.

    Returns:
        {
            "modified": [Path, ...],
            "added": [Path, ...],
            "deleted": [Path, ...]
        }
    """
    changes = {"modified": [], "added": [], "deleted": []}

    # Tracked files changes
    if since_commit:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "diff", "--name-status", since_commit, "HEAD"],
            capture_output=True,
            text=True,
        )
    else:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "diff", "--name-status", "HEAD"],
            capture_output=True,
            text=True,
        )

    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        status, file_path_str = parts[0], parts[1]
        file_path = repo_path / file_path_str

        if status == "M":
            changes["modified"].append(file_path)
        elif status == "A":
            changes["added"].append(file_path)
        elif status == "D":
            changes["deleted"].append(file_path)

    # Untracked new files
    result = subprocess.run(
        ["git", "-C", str(repo_path), "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.strip().splitlines():
        if line:
            changes["added"].append(repo_path / line)

    return changes
