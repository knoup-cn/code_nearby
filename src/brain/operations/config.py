"""知识库配置管理。"""
from __future__ import annotations

from pathlib import Path

from brain import config, git_utils


def needs_overwrite(path: Path) -> bool:
    """返回初始化是否会替换现有目录。"""
    return path.exists() and any(path.iterdir())


def init_config(
    git_repo: str | None, kb_path: Path, overwrite: bool = False
) -> tuple[bool, str]:
    """初始化知识库配置。

    Args:
        git_repo: 知识库的 Git 仓库 URL（读写）
        kb_path: 知识库仓库的解析后的本地路径
        overwrite: 是否覆盖已有的非空目录

    Returns:
        (success, message)
    """
    if not git_repo:
        return False, "Git repository is required (knowledge base is stored in git)"

    git_repo = git_repo.strip()
    resolved_path = str(kb_path)

    # 知识库仓库：测试连接并克隆
    success, message = git_utils.test_git_connection(git_repo)
    if not success:
        return False, f"Git connection failed: {message}"

    success, message = git_utils.clone_repo(git_repo, kb_path, overwrite=overwrite)
    if not success:
        return False, f"Clone failed: {message}"

    # 保存配置（两个字段都是必需的）
    cfg = {
        "git_repo": git_repo,
        "local_path": resolved_path,
    }
    config.save_config(cfg)
    return True, f"Knowledge base initialized at {resolved_path}"


def get_status() -> dict | None:
    """Get current configuration."""
    return config.load_config() if config.is_initialized() else None


def clear_config() -> bool:
    """Clear configuration."""
    if not config.is_initialized():
        return False
    config.get_config_path().unlink()
    return True


def is_git_repo(path: Path) -> bool:
    """Check if path is a Git repository."""
    return git_utils.is_git_repo(path)
