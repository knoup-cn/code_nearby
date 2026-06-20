"""Configuration management."""
from __future__ import annotations

import json
from pathlib import Path


def get_config_path() -> Path:
    """Get configuration file path."""
    config_dir = Path.home() / ".config" / "brain"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def load_config() -> dict:
    """Load configuration."""
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
    """Save configuration."""
    if not validate_config(config):
        raise ValueError(
            "Invalid config: git_repo and local_path must both exist or both be absent"
        )
    get_config_path().write_text(json.dumps(config, indent=2))


def validate_config(config: dict) -> bool:
    """Validate configuration.

    Config must be either empty (uninitialized) or contain both knowledge base
    fields: git_repo and local_path. Pure local mode (local_path without
    git_repo) is not supported.
    """
    if not config:
        return True
    return "git_repo" in config and "local_path" in config


def is_initialized() -> bool:
    """Check if brain is initialized with a valid knowledge base."""
    try:
        config = load_config()
        return bool(config.get("git_repo") and config.get("local_path"))
    except (ValueError, json.JSONDecodeError):
        return False
