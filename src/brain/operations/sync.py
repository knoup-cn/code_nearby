"""知识库 Git 同步。"""

from __future__ import annotations

from pathlib import Path

from brain import git_utils


def sync_knowledge_base(kb_path: Path, project_path: Path, changes_summary: str) -> dict:
    """提交并推送知识库更改。

    Args:
        kb_path: 知识库根路径
        project_path: 源项目路径（用于提交消息）
        changes_summary: 更改摘要（如 "3 added, 2 modified, 1 deleted"）

    Returns:
        {
            "success": bool,
            "commit": str | None,  # 成功时的提交哈希
            "pushed": bool,  # 是否推送成功
            "error": str | None
        }
    """
    # 检查知识库是否为 git 仓库
    if not git_utils.is_git_repo(kb_path):
        return {
            "success": False,
            "commit": None,
            "pushed": False,
            "error": "Knowledge base is not a git repository",
        }

    # 检查是否有更改
    if not git_utils.has_changes(kb_path):
        return {
            "success": True,
            "commit": None,
            "pushed": False,
            "error": None,
        }

    try:
        # 获取项目标识用于提交消息
        remote_url = git_utils.get_remote_url(project_path)
        if remote_url:
            identity = git_utils.parse_repo_identity(remote_url)
            project_name = f"{identity[0]}/{identity[1]}" if identity else project_path.name
        else:
            project_name = project_path.name

        # 暂存所有更改
        git_utils.git_add(kb_path)

        # 创建提交
        commit_message = f"Update {project_name}: {changes_summary}"
        commit_hash = git_utils.git_commit(kb_path, commit_message)

        # 推送到远程
        pushed = False
        push_error = None
        try:
            git_utils.git_push(kb_path)
            pushed = True
        except git_utils.GitCommandError as e:
            push_error = str(e)

        return {
            "success": True,
            "commit": commit_hash,
            "pushed": pushed,
            "error": push_error,
        }

    except git_utils.GitCommandError as e:
        return {
            "success": False,
            "commit": None,
            "pushed": False,
            "error": str(e),
        }
