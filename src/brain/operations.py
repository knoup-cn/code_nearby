"""Core operations (business logic)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from brain import config


def init_config(git_repo: str | None, vault_path: Path, overwrite: bool = False) -> tuple[bool, str]:
    """Initialize knowledge base configuration.

    Args:
        git_repo: Git repository URL (required for knowledge base)
        vault_path: Resolved path to local directory for knowledge base
        overwrite: Whether to overwrite existing non-empty directory

    Returns:
        (success, message)
    """
    if not git_repo:
        return False, "Git repository is required (knowledge base is stored in git)"

    git_repo = git_repo.strip()
    resolved_path = str(vault_path)

    # Check if directory is non-empty
    if vault_path.exists() and any(vault_path.iterdir()):
        if not overwrite:
            return False, "Directory not empty"
        # Clear directory
        import shutil
        shutil.rmtree(vault_path)

    # Test git connection
    success, message = config.test_git_connection(git_repo)
    if not success:
        return False, f"Git connection failed: {message}"

    # Clone repository to local path
    success, message = config.clone_repo(git_repo, vault_path)
    if not success:
        return False, f"Clone failed: {message}"

    # Save configuration (both fields required)
    cfg = {
        "git_repo": git_repo,
        "local_path": resolved_path,
    }
    config.save_config(cfg)
    return True, f"Knowledge base initialized at {resolved_path}"


def get_status() -> dict | None:
    """Get current configuration."""
    return config.load_config() if config.is_initialized() else None


def clear_config() -> bool:
    """Clear configuration."""
    if not config.is_initialized():
        return False
    config.get_config_path().unlink()
    return True


def is_git_repo(path: Path) -> bool:
    """Check if path is a Git repository."""
    from brain import git_utils

    return git_utils.is_git_repo(path)


def analyze_project(project_path: Path, full_rebuild: bool = False) -> dict:
    """Analyze Git repository incrementally.

    Returns:
        {
            "success": bool,
            "files_analyzed": int,
            "added": int,
            "modified": int,
            "deleted": int,
            "error": str | None
        }
    """
    from brain import analyzer, git_utils, storage

    # Load knowledge base configuration
    cfg = config.load_config()
    local_path = cfg.get("local_path")
    if not local_path:
        return {"success": False, "error": "Knowledge base not initialized"}

    kb_path = Path(local_path)

    # Load project metadata
    metadata = storage.load_project_metadata(kb_path, project_path)

    # Detect changes
    current_commit = git_utils.get_current_commit(project_path)

    if full_rebuild or not metadata:
        # Full analysis: all tracked files
        import subprocess

        result = subprocess.run(
            ["git", "-C", str(project_path), "ls-files"],
            capture_output=True,
            text=True,
        )
        tracked_files = [
            project_path / line for line in result.stdout.strip().splitlines() if line
        ]
        changes = {"modified": [], "added": tracked_files, "deleted": []}
    else:
        # Incremental analysis
        last_commit = metadata.get("last_commit")
        changes = git_utils.get_changed_files(project_path, last_commit)

    # Execute analysis
    for file_path in changes["added"] + changes["modified"]:
        if file_path.exists():
            analyzer.analyze_file(file_path, kb_path, project_path)

    # Clean up deleted files
    for file_path in changes["deleted"]:
        storage.remove_file_from_kb(kb_path, project_path, file_path)

    # Update metadata
    storage.save_project_metadata(
        kb_path,
        project_path,
        {
            "last_analyzed": datetime.now(UTC).isoformat(),
            "last_commit": current_commit,
        },
    )

    total = len(changes["added"]) + len(changes["modified"])
    return {
        "success": True,
        "files_analyzed": total,
        "added": len(changes["added"]),
        "modified": len(changes["modified"]),
        "deleted": len(changes["deleted"]),
        "error": None,
    }
