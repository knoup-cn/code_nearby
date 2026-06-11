"""Knowledge base storage operations."""

from __future__ import annotations

import json
from pathlib import Path


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
