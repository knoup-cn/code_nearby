"""配置管理。"""
from __future__ import annotations

import json
from pathlib import Path


def get_config_path() -> Path:
    """获取配置文件路径。"""
    config_dir = Path.home() / ".config" / "brain"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def load_config() -> dict:
    """加载配置。"""
    path = get_config_path()
    if not path.exists():
        return {}
    config = json.loads(path.read_text())
    if not validate_config(config):
        raise ValueError(
            "Invalid config: git_repo and local_path must both exist or both be absent"
        )
    return config


def save_config(config: dict) -> None:
    """保存配置。"""
    if not validate_config(config):
        raise ValueError(
            "Invalid config: git_repo and local_path must both exist or both be absent"
        )
    get_config_path().write_text(json.dumps(config, indent=2))


def validate_config(config: dict) -> bool:
    """验证配置。

    配置必须为空（未初始化）或同时包含两个知识库字段：
    git_repo 和 local_path。不支持纯本地模式（仅有 local_path 而无
    git_repo）。
    """
    if not config:
        return True
    return "git_repo" in config and "local_path" in config


def is_initialized() -> bool:
    """检查 brain 是否已使用有效的知识库完成初始化。"""
    try:
        config = load_config()
        return bool(config.get("git_repo") and config.get("local_path"))
    except (ValueError, json.JSONDecodeError):
        return False
