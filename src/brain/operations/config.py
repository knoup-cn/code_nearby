"""知识库配置管理。"""

from __future__ import annotations

from brain import config


def clear_config() -> bool:
    """清除配置文件，成功返回 True。"""
    path = config.get_config_path()
    if path.exists():
        path.unlink()
        return True
    return False
