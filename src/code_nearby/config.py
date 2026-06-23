"""配置管理——JSON 文件持久化。"""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path


def get_config_path() -> Path:
    """获取配置文件路径 (``~/.nearby/config.json``)。"""
    nearby_dir = Path.home() / ".nearby"
    nearby_dir.mkdir(parents=True, exist_ok=True)
    return nearby_dir / "config.json"


def load_config() -> dict:
    """加载配置，始终返回包含 local_path 的有效字典。"""
    path = get_config_path()
    if not path.exists():
        return _default_config()

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        warnings.warn(
            f"Failed to parse {path}, using default config. "
            "Fix or delete the file to resolve this warning.",
            stacklevel=2,
        )
        return _default_config()
    except OSError:
        warnings.warn(
            f"Could not read {path}, using default config.",
            stacklevel=2,
        )
        return _default_config()

    if "local_path" not in data:
        return _default_config()
    return data  # type: ignore[no-any-return]


def save_config(config: dict) -> None:
    """保存配置——合并写入 JSON 文件。"""
    path = get_config_path()
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logging.warning("Config file %s is corrupted, backing up and starting fresh", path)
            path.rename(path.with_suffix(".json.corrupted"))
    existing.update(config)
    path.write_text(json.dumps(existing, indent=2) + "\n")


def get_kb_path() -> Path:
    """获取知识库本地路径，不存在则自动创建。

    默认路径为 ``~/.nearby``，可通过 ``~/.nearby/config.json`` 中的
    ``local_path`` 键自定义。
    """
    cfg = load_config()
    kb_path = Path(cfg["local_path"]).expanduser().resolve()
    kb_path.mkdir(parents=True, exist_ok=True)
    return kb_path


def _default_config() -> dict:
    return {"local_path": str(Path.home() / ".nearby")}
