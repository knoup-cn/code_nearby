"""知识库存储操作。"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def get_project_kb_path(kb_path: Path, project_path: Path) -> Path:
    """获取项目的知识库子目录。

    使用完整绝对路径（``/`` 替换为 ``-``），确保不同路径的项目不会冲突。

    .. note::

        路径编码会泄露本机绝对路径（如 ``/home/alice/projects/foo`` →
        ``-home-alice-projects-foo``）。同一项目在不同机器或挂载点下会产生不
        同的 KB 路径，跨设备共享知识库目录时请注意。

    Args:
        kb_path: 知识库根目录
        project_path: 源项目目录

    Returns:
        ``{kb_path}/{abs_path_with_dashes}/`` 格式的路径
    """
    name = project_path.resolve().as_posix().replace("/", "-")
    return kb_path / name


def ensure_project_kb_path(kb_path: Path, project_path: Path) -> Path:
    """确保项目知识库目录存在并返回其路径。

    Args:
        kb_path: 知识库根目录
        project_path: 源项目目录

    Returns:
        项目知识库目录的路径
    """
    project_kb_path = get_project_kb_path(kb_path, project_path)
    project_kb_path.mkdir(parents=True, exist_ok=True)
    return project_kb_path


def _metadata_key(project_path: Path) -> str:
    """将项目路径规范化为元数据 key。

    与 get_project_kb_path 的编码方式一致：resolve 后再序列化。
    """
    return str(project_path.resolve())


def load_project_metadata(kb_path: Path, project_path: Path) -> dict | None:
    """从知识库加载项目元数据。

    返回的是副本，调用方可随意修改。
    """
    metadata_file = kb_path / "metadata.json"
    if not metadata_file.exists():
        return None

    data = json.loads(metadata_file.read_text())
    meta = data.get("projects", {}).get(_metadata_key(project_path))
    return dict(meta) if meta is not None else None


def save_project_metadata(kb_path: Path, project_path: Path, updates: dict) -> None:
    """保存项目元数据到知识库。

    使用原子写入（先写临时文件再 rename），防止并发覆盖和写入中途崩溃
    导致文件损坏。
    """
    metadata_file = kb_path / "metadata.json"
    metadata_file.parent.mkdir(parents=True, exist_ok=True)

    if metadata_file.exists():
        data = json.loads(metadata_file.read_text())
    else:
        data = {"version": "1", "projects": {}}

    project_key = _metadata_key(project_path)
    if project_key not in data["projects"]:
        data["projects"][project_key] = {}

    data["projects"][project_key].update(updates)

    # 原子写入：先写临时文件，再 os.replace（同文件系统内为原子操作）
    tmp_file = metadata_file.with_suffix(metadata_file.suffix + ".tmp")
    try:
        tmp_file.write_text(json.dumps(data, indent=2))
        os.replace(tmp_file, metadata_file)
    except Exception:
        # 清理临时文件，避免残留
        if tmp_file.exists():
            tmp_file.unlink()
        raise
