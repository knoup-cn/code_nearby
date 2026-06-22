"""知识库存储操作。"""

from __future__ import annotations

import json
from pathlib import Path

from brain import git_utils


def get_project_kb_path(kb_path: Path, project_path: Path) -> Path | None:
    """根据 org/project 结构获取项目的知识库子目录。

    Args:
        kb_path: 知识库根目录
        project_path: 源项目目录

    Returns:
        格式为 {kb_path}/{org}/{project}/ 的路径，若无法确定仓库身份则返回 None
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
    """确保项目知识库目录存在并返回其路径。

    Args:
        kb_path: 知识库根目录
        project_path: 源项目目录

    Returns:
        项目知识库目录的路径

    Raises:
        RuntimeError: 若无法确定仓库身份
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
    """从知识库加载项目元数据。"""
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
    """Remove an analyzed file's markdown from the knowledge base.

    Mirrors :func:`brain.analyzer.analyze_file`'s path mapping: a source file at
    ``{project}/<rel>.py`` is stored at ``{kb}/<rel>.md``, so deletion targets
    the same relative path. Non-Python files never produced markdown, so they
    are ignored.

    Args:
        kb_path: Project's knowledge base path (org/project/)
        project_path: Source project path
        file_path: Deleted source file (absolute path under project_path)
    """
    if file_path.suffix != ".py":
        return
    try:
        relative_path = file_path.relative_to(project_path)
    except ValueError:
        return
    (kb_path / relative_path.with_suffix(".md")).unlink(missing_ok=True)
