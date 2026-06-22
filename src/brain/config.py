"""配置管理——JSON 文件持久化。"""

from __future__ import annotations

import json
from pathlib import Path


def get_config_path() -> Path:
    """获取配置文件路径 (``~/.brain/config.json``)。"""
    brain_dir = Path.home() / ".brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    return brain_dir / "config.json"


def load_config() -> dict:
    """加载配置，始终返回包含 local_path 的有效字典。"""
    path = get_config_path()
    if not path.exists():
        return _default_config()

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return _default_config()

    if "local_path" not in data:
        return _default_config()
    return data


def save_config(config: dict) -> None:
    """保存配置——合并写入 JSON 文件。"""
    path = get_config_path()
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    existing.update({k: str(v) for k, v in config.items()})
    path.write_text(json.dumps(existing, indent=2) + "\n")


def get_kb_path() -> Path:
    """获取知识库本地路径，不存在则自动创建。

    默认路径为 ``~/.brain``，可通过 ``~/.brain/config.json`` 中的
    ``local_path`` 键自定义。
    """
    cfg = load_config()
    kb_path = Path(cfg["local_path"]).expanduser().resolve()
    kb_path.mkdir(parents=True, exist_ok=True)
    return kb_path


def _default_config() -> dict:
    return {"local_path": str(Path.home() / ".brain")}
