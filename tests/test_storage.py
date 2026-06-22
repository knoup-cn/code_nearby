"""Test storage operations."""

from __future__ import annotations

from brain import storage


def test_get_project_kb_path_uses_kb_name(tmp_path):
    """kb_name 优先于目录名。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "my-project"
    project_path.mkdir()

    result = storage.get_project_kb_path(kb_path, project_path, kb_name="custom-name")

    assert result == kb_path / "custom-name"


def test_get_project_kb_path_falls_back_to_directory_name(tmp_path):
    """未提供 kb_name 时回退到项目目录名。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "my-project"
    project_path.mkdir()

    result = storage.get_project_kb_path(kb_path, project_path)

    assert result == kb_path / "my-project"


def test_get_project_kb_path_resolves_symlink_name(tmp_path):
    """resolve() 后使用真实目录名。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "real-project"
    project_path.mkdir()

    result = storage.get_project_kb_path(kb_path, project_path)

    assert result == kb_path / "real-project"


def test_ensure_project_kb_path_creates_directory(tmp_path):
    """ensure_project_kb_path 创建目录结构。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"
    project_path.mkdir()

    result = storage.ensure_project_kb_path(kb_path, project_path)

    assert result.exists()
    assert result.is_dir()
    assert result == kb_path / "project"


def test_ensure_project_kb_path_with_kb_name(tmp_path):
    """kb_name 显式指定时使用该名称创建目录。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"
    project_path.mkdir()

    result = storage.ensure_project_kb_path(kb_path, project_path, kb_name="explicit")

    assert result.exists()
    assert result.is_dir()
    assert result == kb_path / "explicit"


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

    storage.save_project_metadata(
        kb_path, project_path, {"last_indexed_at": 1719000000.0}
    )

    metadata = storage.load_project_metadata(kb_path, project_path)
    assert metadata["last_indexed_at"] == 1719000000.0


def test_load_metadata_nonexistent(tmp_path):
    """无元数据文件时返回 None。"""
    kb_path = tmp_path / "kb"
    project_path = tmp_path / "project"

    result = storage.load_project_metadata(kb_path, project_path)

    assert result is None
