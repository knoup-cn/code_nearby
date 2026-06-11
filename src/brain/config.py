"""Configuration management."""
from __future__ import annotations

import json
import subprocess
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
        raise ValueError("Invalid config: git_repo and local_path must both exist or both be absent")
    return config


def save_config(config: dict) -> None:
    """Save configuration."""
    if not validate_config(config):
        raise ValueError("Invalid config: git_repo and local_path must both exist or both be absent")
    get_config_path().write_text(json.dumps(config, indent=2))


def validate_config(config: dict) -> bool:
    """Validate configuration.

    Config must be either empty (uninitialized) or contain both git_repo and local_path.
    Pure local mode (local_path without git_repo) is not supported.
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


def test_git_connection(repo_url: str) -> tuple[bool, str]:
    """Test git repository connectivity."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", repo_url],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (True, "Connected") if result.returncode == 0 else (False, result.stderr.strip())
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def clone_repo(repo_url: str, target_path: Path) -> tuple[bool, str]:
    """Clone git repository safely using temporary directory."""
    import shutil
    import tempfile

    target_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=target_path.parent) as tmp_dir:
        tmp_path = Path(tmp_dir)

        try:
            result = subprocess.run(
                ["git", "clone", repo_url, str(tmp_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                return False, result.stderr.strip()

            # Clone succeeded, move to target
            if target_path.exists():
                shutil.rmtree(target_path)
            shutil.move(str(tmp_path), str(target_path))

            return True, "Cloned"

        except subprocess.TimeoutExpired:
            return False, "Timeout"
        except Exception as e:
            return False, str(e)
