"""知识库 Git 同步。"""
from __future__ import annotations

from pathlib import Path

from brain import git_utils


def sync_knowledge_base(
    kb_path: Path, project_path: Path, changes_summary: str
) -> dict:
    """Commit and push knowledge base changes.

    Args:
        kb_path: Knowledge base root path
        project_path: Source project path (for commit message)
        changes_summary: Summary of changes (e.g., "3 added, 2 modified, 1 deleted")

    Returns:
        {
            "success": bool,
            "commit": str | None,  # Commit hash if successful
            "pushed": bool,  # Whether push succeeded
            "error": str | None
        }
    """
    # Check if KB is a git repository
    if not git_utils.is_git_repo(kb_path):
        return {
            "success": False,
            "commit": None,
            "pushed": False,
            "error": "Knowledge base is not a git repository",
        }

    # Check if there are changes
    if not git_utils.has_changes(kb_path):
        return {
            "success": True,
            "commit": None,
            "pushed": False,
            "error": None,
        }

    try:
        # Get project identity for commit message
        remote_url = git_utils.get_remote_url(project_path)
        if remote_url:
            identity = git_utils.parse_repo_identity(remote_url)
            project_name = f"{identity[0]}/{identity[1]}" if identity else project_path.name
        else:
            project_name = project_path.name

        # Stage all changes
        git_utils.git_add(kb_path)

        # Create commit
        commit_message = f"Update {project_name}: {changes_summary}"
        commit_hash = git_utils.git_commit(kb_path, commit_message)

        # Push to remote
        pushed = False
        push_error = None
        try:
            git_utils.git_push(kb_path)
            pushed = True
        except git_utils.GitCommandError as e:
            push_error = str(e)

        return {
            "success": True,
            "commit": commit_hash,
            "pushed": pushed,
            "error": push_error,
        }

    except git_utils.GitCommandError as e:
        return {
            "success": False,
            "commit": None,
            "pushed": False,
            "error": str(e),
        }
