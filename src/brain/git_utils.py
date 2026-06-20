"""Git repository operations.

This module supports two Git repository contexts:
1. Knowledge Base (KB) repository - stores generated knowledge base, supports read/write
2. Source repository - the project being analyzed, read-only operations

Functions are generic and work with any git repository path.
Callers are responsible for distinguishing between KB and source repositories.
"""

from __future__ import annotations

import shutil
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


def get_current_commit(repo_path: Path) -> str | None:
    """Get current HEAD commit hash."""
    try:
        result = _run_git(repo_path, ["rev-parse", "HEAD"])
        return result.stdout.strip()
    except GitCommandError:
        return None


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
    diff_args = (
        ["diff", "--name-status", since_commit, "HEAD"]
        if since_commit
        else ["diff", "--name-status", "HEAD"]
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
    result = _run_git(repo_path, ["ls-files", "--others", "--exclude-standard"])
    for line in result.stdout.strip().splitlines():
        if line:
            changes["added"].append(repo_path / line)

    return changes


def validate_safe_delete_path(path: Path) -> tuple[bool, str]:
    """Validate that a path is safe to delete recursively."""
    if path.is_symlink():
        return False, f"Refusing to delete symlink: {path}"

    try:
        resolved = path.expanduser().resolve()
        home = Path.home().resolve()
        home_config = (home / ".config").resolve()
        config_dir = (home / ".config" / "brain").resolve()
        cwd = Path.cwd().resolve()
    except OSError as e:
        return False, f"Cannot resolve path: {e}"

    protected = {
        Path(resolved.anchor),
        home,
        home_config,
        config_dir,
        cwd,
    }

    if resolved in protected:
        return False, f"Refusing to delete protected path: {resolved}"

    if len(resolved.parts) <= 2:
        return False, f"Refusing to delete shallow path: {resolved}"

    if resolved in cwd.parents:
        return False, f"Refusing to delete parent of current working directory: {resolved}"

    if resolved in config_dir.parents:
        return False, f"Refusing to delete parent of Brain config directory: {resolved}"

    if not resolved.exists():
        return False, f"Path does not exist: {resolved}"

    if not resolved.is_dir():
        return False, f"Path is not a directory: {resolved}"

    return True, ""


def test_git_connection(repo_url: str) -> tuple[bool, str]:
    """Test git repository connectivity."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", repo_url],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (True, "Connected") if result.returncode == 0 else (False, result.stderr.strip())
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


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


def clone_repo(repo_url: str, target_path: Path, overwrite: bool = False) -> tuple[bool, str]:
    """Clone git repository into the target path."""
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists() and any(target_path.iterdir()):
        if not overwrite:
            return False, "Directory not empty"
        safe, message = validate_safe_delete_path(target_path)
        if not safe:
            return False, message
        shutil.rmtree(target_path)

    try:
        result = subprocess.run(
            ["git", "clone", repo_url, str(target_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            return False, result.stderr.strip()

        return True, "Cloned"

    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def has_changes(repo_path: Path) -> bool:
    """Check if repository has uncommitted changes.

    Returns:
        True if there are changes (staged or unstaged), False otherwise
    """
    try:
        # Check both staged and unstaged changes
        result = _run_git(repo_path, ["status", "--porcelain"])
        return bool(result.stdout.strip())
    except GitCommandError:
        return False


def get_repo_status(repo_path: Path) -> dict[str, list[str]]:
    """Get repository status categorized by change type.

    Returns:
        {
            "modified": [relative_path, ...],
            "added": [relative_path, ...],
            "deleted": [relative_path, ...],
            "untracked": [relative_path, ...]
        }
    """
    status = {"modified": [], "added": [], "deleted": [], "untracked": []}

    try:
        result = _run_git(repo_path, ["status", "--porcelain"])
        for line in result.stdout.splitlines():  # Don't strip() - we need the exact format
            if not line or len(line) < 4:
                continue

            # Format: "XY filename" where X=index, Y=worktree
            # XY is always 2 chars, followed by a space, then filename
            xy = line[:2]
            filepath = line[3:]  # Skip "XY " (2 chars + space)

            if xy == "??":
                status["untracked"].append(filepath)
            elif "M" in xy:
                status["modified"].append(filepath)
            elif "A" in xy:
                status["added"].append(filepath)
            elif "D" in xy:
                status["deleted"].append(filepath)
    except GitCommandError:
        pass

    return status


def git_add(repo_path: Path, paths: list[str] | None = None) -> None:
    """Stage changes in repository.

    Args:
        repo_path: Git repository path
        paths: Specific paths to stage, or None to stage all changes

    Raises:
        GitCommandError: If staging fails
    """
    if paths:
        _run_git(repo_path, ["add", "--", *paths])
    else:
        _run_git(repo_path, ["add", "-A"])


def git_commit(repo_path: Path, message: str, author: str | None = None) -> str:
    """Create a commit.

    Args:
        repo_path: Git repository path
        message: Commit message
        author: Optional author in format "Name <email>"

    Returns:
        Commit hash

    Raises:
        GitCommandError: If commit fails
    """
    args = ["commit", "-m", message]
    if author:
        args.extend(["--author", author])

    _run_git(repo_path, args)

    # Get the commit hash
    result = _run_git(repo_path, ["rev-parse", "HEAD"])
    return result.stdout.strip()


def git_push(repo_path: Path, remote: str = "origin", branch: str | None = None) -> None:
    """Push commits to remote.

    Args:
        repo_path: Git repository path
        remote: Remote name (default: origin)
        branch: Branch name, or None to push current branch

    Raises:
        GitCommandError: If push fails
    """
    args = ["push", remote]
    if branch:
        args.append(branch)

    _run_git(repo_path, args)


def get_current_branch(repo_path: Path) -> str | None:
    """Get current branch name.

    Returns:
        Branch name or None if detached HEAD
    """
    try:
        result = _run_git(repo_path, ["branch", "--show-current"])
        branch = result.stdout.strip()
        return branch if branch else None
    except GitCommandError:
        return None
