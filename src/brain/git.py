from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a Git command cannot be completed."""


@dataclass(frozen=True)
class RepositoryStatus:
    path: Path
    branch: str
    changes: tuple[str, ...]


def find_repositories(root: Path, *, max_depth: int = 4) -> list[Path]:
    if max_depth < 0:
        raise GitError("--max-depth must be zero or greater")

    root = root.expanduser().resolve()
    if not root.exists():
        raise GitError(f"path does not exist: {root}")
    if not root.is_dir():
        raise GitError(f"path is not a directory: {root}")

    repositories: list[Path] = []
    stack: list[tuple[Path, int]] = [(root, 0)]

    while stack:
        current, depth = stack.pop()
        if _is_git_repository(current):
            repositories.append(current)
            continue

        if depth >= max_depth:
            continue

        try:
            children = sorted(child for child in current.iterdir() if child.is_dir())
        except PermissionError:
            continue

        for child in reversed(children):
            if child.name in {".git", ".venv", "__pycache__", "node_modules"}:
                continue
            stack.append((child, depth + 1))

    return sorted(repositories)


def repository_status(path: Path) -> RepositoryStatus:
    repo_path = _git_root(path)
    branch = _run_git(repo_path, "branch", "--show-current").strip() or "HEAD"
    status_output = _run_git(repo_path, "status", "--porcelain").splitlines()
    return RepositoryStatus(path=repo_path, branch=branch, changes=tuple(status_output))


def _is_git_repository(path: Path) -> bool:
    git_dir = path / ".git"
    return git_dir.is_dir() or git_dir.is_file()


def _git_root(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.exists():
        raise GitError(f"path does not exist: {path}")

    start = path if path.is_dir() else path.parent
    try:
        output = _run_git(start, "rev-parse", "--show-toplevel")
    except GitError as exc:
        raise GitError(f"not a Git repository: {path}") from exc

    return Path(output.strip()).resolve()


def _run_git(cwd: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable was not found") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or "git command failed"
        raise GitError(message) from exc

    return completed.stdout
