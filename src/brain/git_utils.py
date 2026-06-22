"""Git 仓库操作——用于源项目变更检测。"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitCommandError(RuntimeError):
    """Raised when a git command fails."""


def _run_git(repo_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run git command and raise on failure."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() or e.stdout.strip() or f"exit code {e.returncode}"
        raise GitCommandError(f"git {args[0]} failed: {stderr}") from e
    except OSError as e:
        raise GitCommandError(f"git {args[0]} failed: {e}") from e


def is_git_repo(path: Path) -> bool:
    """Check if path is a Git repository."""
    return (path / ".git").exists()


def require_current_commit(repo_path: Path) -> str:
    """Get current HEAD commit hash or raise when unavailable."""
    result = _run_git(repo_path, ["rev-parse", "HEAD"])
    commit = result.stdout.strip()
    if not commit:
        raise GitCommandError("git rev-parse failed: empty HEAD")
    return commit


def get_tracked_files(repo_path: Path) -> list[Path]:
    """Get tracked files in a Git repository."""
    result = _run_git(repo_path, ["ls-files"])
    return [repo_path / line for line in result.stdout.strip().splitlines() if line]


def get_untracked_files(repo_path: Path) -> list[Path]:
    """Get untracked, non-ignored files in a Git repository."""
    result = _run_git(repo_path, ["ls-files", "--others", "--exclude-standard"])
    return [repo_path / line for line in result.stdout.strip().splitlines() if line]


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

    # Tracked files changes since the reference commit, compared against the
    # working tree (not HEAD) so uncommitted edits are detected too.
    # --no-renames forces renames to surface as delete + add, matching the
    # M/A/D parsing below.
    diff_args = (
        ["diff", "--name-status", "--no-renames", since_commit]
        if since_commit
        else ["diff", "--name-status", "--no-renames", "HEAD"]
    )
    result = _run_git(repo_path, diff_args)

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
    changes["added"].extend(get_untracked_files(repo_path))

    return changes


def get_remote_url(repo_path: Path) -> str | None:
    """Get remote origin URL from a Git repository.

    Returns:
        Remote URL or None if not found
    """
    try:
        result = _run_git(repo_path, ["remote", "get-url", "origin"])
        return result.stdout.strip()
    except GitCommandError:
        return None


def parse_repo_identity(repo_url: str) -> tuple[str, str] | None:
    """Parse organization and project name from Git repository URL.

    Supports formats:
    - https://github.com/org/project.git
    - git@github.com:org/project.git
    - https://gitlab.com/org/project

    Returns:
        (organization, project) or None if parsing failed
    """
    if not repo_url:
        return None

    # Remove .git suffix
    url = repo_url.rstrip("/").removesuffix(".git")

    # Handle SSH format: git@host:org/project
    if "@" in url and ":" in url:
        parts = url.split(":")
        if len(parts) >= 2:
            path = parts[-1]
            segments = path.split("/")
            if len(segments) >= 2:
                return segments[-2], segments[-1]
        return None

    # Handle HTTPS format: https://host/org/project
    if "/" in url:
        segments = url.split("/")
        # Need at least protocol, host, org, project: ['https:', '', 'host', 'org', 'project']
        if len(segments) >= 5 and segments[0] in ("https:", "http:", "git:"):
            return segments[-2], segments[-1]

    return None
