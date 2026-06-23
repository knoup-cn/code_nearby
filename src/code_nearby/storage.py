"""知识库存储操作。"""

from __future__ import annotations

import json
from pathlib import Path


def get_project_kb_path(
    kb_path: Path, project_path: Path, kb_name: str | None = None
) -> Path:
    """获取项目的知识库子目录。

    优先使用显式传入的 *kb_name*，否则使用项目目录名。

    Args:
        kb_path: 知识库根目录
        project_path: 源项目目录
        kb_name: 显式知识库名称（如 CLI ``--kb-name`` 传入），
            用于避免同名目录冲突

    Returns:
        ``{kb_path}/{kb_name}/`` 或 ``{kb_path}/{project_name}/`` 格式的路径
    """
    name = kb_name or project_path.resolve().name
    return kb_path / name


def ensure_project_kb_path(
    kb_path: Path, project_path: Path, kb_name: str | None = None
) -> Path:
    """确保项目知识库目录存在并返回其路径。

    Args:
        kb_path: 知识库根目录
        project_path: 源项目目录
        kb_name: 显式知识库名称

    Returns:
        项目知识库目录的路径
    """
    project_kb_path = get_project_kb_path(kb_path, project_path, kb_name=kb_name)
    project_kb_path.mkdir(parents=True, exist_ok=True)
    return project_kb_path


def load_project_metadata(kb_path: Path, project_path: Path) -> dict | None:
    """从知识库加载项目元数据。"""
    metadata_file = kb_path / "metadata.json"
    if not metadata_file.exists():
        return None

    data = json.loads(metadata_file.read_text())
    return data.get("projects", {}).get(str(project_path))


def save_project_metadata(kb_path: Path, project_path: Path, updates: dict) -> None:
    """保存项目元数据到知识库。"""
    metadata_file = kb_path / "metadata.json"
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
