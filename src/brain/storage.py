"""Knowledge base storage operations."""

from __future__ import annotations

import json
from pathlib import Path

from brain import git_utils


def get_project_kb_path(kb_path: Path, project_path: Path) -> Path | None:
    """Get knowledge base subdirectory for a project based on org/project structure.

    Args:
        kb_path: Knowledge base root directory
        project_path: Source project directory

    Returns:
        Path like {kb_path}/{org}/{project}/ or None if repo identity cannot be determined
    """
    remote_url = git_utils.get_remote_url(project_path)
    if not remote_url:
        return None

    identity = git_utils.parse_repo_identity(remote_url)
    if not identity:
        return None

    org, project = identity
    return kb_path / org / project


def ensure_project_kb_path(kb_path: Path, project_path: Path) -> Path:
    """Ensure project knowledge base directory exists and return its path.

    Args:
        kb_path: Knowledge base root directory
        project_path: Source project directory

    Returns:
        Path to project's knowledge base directory

    Raises:
        RuntimeError: If repository identity cannot be determined
    """
    project_kb_path = get_project_kb_path(kb_path, project_path)
    if not project_kb_path:
        raise RuntimeError(
            f"Cannot determine repository identity for {project_path}. "
            "Ensure the repository has a remote 'origin' configured."
        )

    project_kb_path.mkdir(parents=True, exist_ok=True)
    return project_kb_path


def load_project_metadata(kb_path: Path, project_path: Path) -> dict | None:
    """Load project metadata from knowledge base."""
    metadata_file = kb_path / ".brain" / "metadata.json"
    if not metadata_file.exists():
        return None

    data = json.loads(metadata_file.read_text())
    return data.get("projects", {}).get(str(project_path))


def save_project_metadata(kb_path: Path, project_path: Path, updates: dict) -> None:
    """Save project metadata to knowledge base."""
    metadata_file = kb_path / ".brain" / "metadata.json"
    metadata_file.parent.mkdir(parents=True, exist_ok=True)

    if metadata_file.exists():
        data = json.loads(metadata_file.read_text())
    else:
        data = {"version": "1", "projects": {}}

    project_key = str(project_path)
    if project_key not in data["projects"]:
        data["projects"][project_key] = {}

    data["projects"][project_key].update(updates)
    metadata_file.write_text(json.dumps(data, indent=2))


def remove_file_from_kb(kb_path: Path, project_path: Path, file_path: Path) -> None:
    """Remove analyzed file from knowledge base."""
    # TODO: Implement deletion logic when analyzer is ready
    pass
