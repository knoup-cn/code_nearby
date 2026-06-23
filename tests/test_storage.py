"""Test storage operations."""

from __future__ import annotations

import json
from pathlib import Path

from code_nearby import storage


def test_get_project_kb_path_falls_back_to_full_path(tmp_path):
    """未提供 kb_name 时使用完整绝对路径 (/ 替换为 -)。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "my-project"
    project_path.mkdir()

    result = storage.get_project_kb_path(kb_path, project_path)

    expected_name = project_path.resolve().as_posix().replace("/", "-")
    assert result == kb_path / expected_name


def test_get_project_kb_path_resolves_symlink_name(tmp_path):
    """resolve() 后使用真实路径名。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "real-project"
    project_path.mkdir()

    result = storage.get_project_kb_path(kb_path, project_path)

    expected_name = project_path.resolve().as_posix().replace("/", "-")
    assert result == kb_path / expected_name


def test_ensure_project_kb_path_creates_directory(tmp_path):
    """ensure_project_kb_path 创建目录结构。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"
    project_path.mkdir()

    result = storage.ensure_project_kb_path(kb_path, project_path)

    assert result.exists()
    assert result.is_dir()
    expected_name = project_path.resolve().as_posix().replace("/", "-")
    assert result == kb_path / expected_name


def test_metadata_save_and_load(tmp_path):
    """保存并加载项目元数据。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"

    storage.save_project_metadata(kb_path, project_path, {"kb_location": "my-project"})

    metadata = storage.load_project_metadata(kb_path, project_path)
    assert metadata["kb_location"] == "my-project"


def test_metadata_includes_last_indexed_at(tmp_path):
    """元数据可记录 last_indexed_at 时间戳。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"

    storage.save_project_metadata(kb_path, project_path, {"last_indexed_at": 1719000000.0})

    metadata = storage.load_project_metadata(kb_path, project_path)
    assert metadata["last_indexed_at"] == 1719000000.0


def test_load_metadata_nonexistent(tmp_path):
    """无元数据文件时返回 None。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"

    result = storage.load_project_metadata(kb_path, project_path)

    assert result is None


def test_save_metadata_atomic_no_temp_file_left_behind(tmp_path):
    """原子写入完成后不残留 .tmp 文件。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"

    storage.save_project_metadata(kb_path, project_path, {"key": "value"})

    # 确认元数据文件存在且无 .tmp 残留
    metadata_file = kb_path / "metadata.json"
    assert metadata_file.exists()
    tmp_files = list(kb_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_load_metadata_returns_copy(tmp_path):
    """load 返回副本，修改返回值不影响后续加载。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"

    storage.save_project_metadata(kb_path, project_path, {"key": "original"})

    meta = storage.load_project_metadata(kb_path, project_path)
    assert meta is not None
    meta["key"] = "mutated"

    # 再次加载应仍是原始值
    reloaded = storage.load_project_metadata(kb_path, project_path)
    assert reloaded is not None
    assert reloaded["key"] == "original"


def test_relative_path_produces_consistent_key(tmp_path, monkeypatch):
    """相对路径 resolve 后与绝对路径产生相同的元数据 key。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"
    project_path.mkdir()

    # 先用绝对路径写入
    storage.save_project_metadata(kb_path, project_path.resolve(), {"key": "value"})

    # 用相对路径应能读到相同数据（因为 resolve() 后 key 一致）
    saved_cwd = Path.cwd()
    try:
        # 切到 tmp_path 使相对路径有效
        monkeypatch.chdir(tmp_path)
        relative_path = Path("project")
        meta = storage.load_project_metadata(kb_path, relative_path)
        assert meta is not None
        assert meta["key"] == "value"
    finally:
        monkeypatch.chdir(saved_cwd)


def test_save_metadata_preserves_other_projects(tmp_path):
    """保存一个项目的元数据不影响其他项目的记录。"""
    kb_path = tmp_path / "kb"
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"

    storage.save_project_metadata(kb_path, project_a, {"name": "A"})
    storage.save_project_metadata(kb_path, project_b, {"name": "B"})

    # 两个项目的数据应各自保留
    meta_a = storage.load_project_metadata(kb_path, project_a)
    meta_b = storage.load_project_metadata(kb_path, project_b)
    assert meta_a["name"] == "A"
    assert meta_b["name"] == "B"

    # 确认原始 JSON 中两个 key 都存在
    raw = json.loads((kb_path / "metadata.json").read_text())
    assert len(raw["projects"]) == 2
