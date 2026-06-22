"""知识库配置管理。"""

from __future__ import annotations

from pathlib import Path

from brain import config, git_utils


def get_status() -> dict:
    """获取当前配置，始终返回有效字典。"""
    return config.load_config()


def clear_config() -> bool:
    """清除配置文件，成功返回 True。"""
    path = config.get_config_path()
    if path.exists():
        path.unlink()
        return True
    return False


def is_git_repo(path: Path) -> bool:
    """检查路径是否为 Git 仓库。"""
    return git_utils.is_git_repo(path)
