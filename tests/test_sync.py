"""Tests for knowledge base synchronization."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from brain import git_utils
from brain.operations import analysis, sync


@pytest.fixture
def mock_kb_repo(tmp_path: Path) -> Path:
    """Create a mock knowledge base repository."""
    kb_path = tmp_path / "kb"
    kb_path.mkdir()

    # Initialize as git repo
    subprocess.run(["git", "init"], cwd=kb_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=kb_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=kb_path,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    (kb_path / "README.md").write_text("# Knowledge Base\n")
    subprocess.run(["git", "add", "README.md"], cwd=kb_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=kb_path,
        check=True,
        capture_output=True,
    )

    return kb_path


@pytest.fixture
def mock_project_repo(tmp_path: Path) -> Path:
    """Create a mock project repository."""
    project_path = tmp_path / "project"
    project_path.mkdir()

    # Initialize as git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=project_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=project_path,
        check=True,
        capture_output=True,
    )

    # Add remote
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/project.git"],
        cwd=project_path,
        check=True,
        capture_output=True,
    )

    return project_path


class TestGitUtilsSync:
    """Test git_utils synchronization functions."""

    def test_has_changes_true(self, mock_kb_repo: Path) -> None:
        """Test has_changes detects changes."""
        # Create a new file
        (mock_kb_repo / "new_file.md").write_text("# New File\n")

        assert git_utils.has_changes(mock_kb_repo) is True

    def test_has_changes_false(self, mock_kb_repo: Path) -> None:
        """Test has_changes returns False for clean repo."""
        assert git_utils.has_changes(mock_kb_repo) is False

    def test_get_repo_status_untracked(self, mock_kb_repo: Path) -> None:
        """Test get_repo_status detects untracked files."""
        (mock_kb_repo / "untracked.md").write_text("# Untracked\n")

        status = git_utils.get_repo_status(mock_kb_repo)

        assert "untracked.md" in status["untracked"]
        assert len(status["modified"]) == 0
        assert len(status["added"]) == 0
        assert len(status["deleted"]) == 0

    def test_get_repo_status_modified(self, mock_kb_repo: Path) -> None:
        """Test get_repo_status detects modified files."""
        # Modify existing file
        readme = mock_kb_repo / "README.md"
        readme.write_text("# Modified\n")

        status = git_utils.get_repo_status(mock_kb_repo)

        # Modified files appear in worktree changes
        # Git status format: " M filename" (space + M + space + filename)
        # The function strips the XY prefix and returns just the filename
        assert len(status["modified"]) > 0
        assert any("README.md" in f for f in status["modified"])

    def test_git_add_all(self, mock_kb_repo: Path) -> None:
        """Test git_add stages all changes."""
        (mock_kb_repo / "file1.md").write_text("# File 1\n")
        (mock_kb_repo / "file2.md").write_text("# File 2\n")

        git_utils.git_add(mock_kb_repo)

        # Verify files are staged
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=mock_kb_repo,
            check=True,
            capture_output=True,
            text=True,
        )

        assert "file1.md" in result.stdout
        assert "file2.md" in result.stdout

    def test_git_add_specific_paths(self, mock_kb_repo: Path) -> None:
        """Test git_add stages specific paths."""
        (mock_kb_repo / "file1.md").write_text("# File 1\n")
        (mock_kb_repo / "file2.md").write_text("# File 2\n")

        git_utils.git_add(mock_kb_repo, paths=["file1.md"])

        # Verify only file1 is staged
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=mock_kb_repo,
            check=True,
            capture_output=True,
            text=True,
        )

        assert "file1.md" in result.stdout
        assert "file2.md" not in result.stdout

    def test_git_commit(self, mock_kb_repo: Path) -> None:
        """Test git_commit creates a commit."""
        # Stage a change
        (mock_kb_repo / "new.md").write_text("# New\n")
        git_utils.git_add(mock_kb_repo)

        # Commit
        commit_hash = git_utils.git_commit(mock_kb_repo, "Test commit")

        # Verify commit exists
        assert len(commit_hash) == 40  # SHA-1 hash length
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=mock_kb_repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "Test commit"

    def test_git_commit_with_author(self, mock_kb_repo: Path) -> None:
        """Test git_commit with custom author."""
        (mock_kb_repo / "new.md").write_text("# New\n")
        git_utils.git_add(mock_kb_repo)

        git_utils.git_commit(mock_kb_repo, "Test commit", author="Custom <custom@example.com>")

        result = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>"],
            cwd=mock_kb_repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "Custom <custom@example.com>"

    def test_get_current_branch(self, mock_kb_repo: Path) -> None:
        """Test get_current_branch returns branch name."""
        branch = git_utils.get_current_branch(mock_kb_repo)

        # Default branch is usually "main" or "master"
        assert branch in ("main", "master")


class TestSyncKnowledgeBase:
    """Test sync_knowledge_base operation."""

    def test_sync_no_git_repo(self, tmp_path: Path, mock_project_repo: Path) -> None:
        """Test sync fails when KB is not a git repo."""
        kb_path = tmp_path / "not_a_repo"
        kb_path.mkdir()

        result = sync.sync_knowledge_base(kb_path, mock_project_repo, "test")

        assert result["success"] is False
        assert "not a git repository" in result["error"]

    def test_sync_no_changes(self, mock_kb_repo: Path, mock_project_repo: Path) -> None:
        """Test sync succeeds with no changes."""
        result = sync.sync_knowledge_base(mock_kb_repo, mock_project_repo, "test")

        assert result["success"] is True
        assert result["commit"] is None
        assert result["pushed"] is False

    def test_sync_with_changes_no_remote(self, mock_kb_repo: Path, mock_project_repo: Path) -> None:
        """Test sync commits changes but fails to push without remote."""
        # Create changes in KB
        (mock_kb_repo / "test_org" / "test_project" / "module.md").parent.mkdir(parents=True)
        (mock_kb_repo / "test_org" / "test_project" / "module.md").write_text("# Module\n")

        result = sync.sync_knowledge_base(
            mock_kb_repo, mock_project_repo, "1 added, 0 modified, 0 deleted"
        )

        # Should succeed in committing
        assert result["success"] is True
        assert result["commit"] is not None
        assert len(result["commit"]) == 40

        # Push should fail (no remote)
        assert result["pushed"] is False
        assert result["error"] is not None

    def test_sync_commit_message(self, mock_kb_repo: Path, mock_project_repo: Path) -> None:
        """Test sync creates correct commit message."""
        (mock_kb_repo / "new.md").write_text("# New\n")

        sync.sync_knowledge_base(mock_kb_repo, mock_project_repo, "2 added, 1 modified, 0 deleted")

        # Check commit message
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=mock_kb_repo,
            check=True,
            capture_output=True,
            text=True,
        )

        assert "test/project" in result.stdout
        assert "2 added, 1 modified, 0 deleted" in result.stdout

    @patch("brain.git_utils.git_push")
    def test_sync_with_successful_push(
        self, mock_push: MagicMock, mock_kb_repo: Path, mock_project_repo: Path
    ) -> None:
        """Test sync with successful push."""
        (mock_kb_repo / "new.md").write_text("# New\n")

        result = sync.sync_knowledge_base(mock_kb_repo, mock_project_repo, "test")

        assert result["success"] is True
        assert result["pushed"] is True
        assert result["error"] is None
        mock_push.assert_called_once()


class TestAnalyzeWithSync:
    """Test run_full_analysis with mock storage."""

    @patch("brain.operations.sync.sync_knowledge_base")
    def test_analyze_without_sync(
        self, mock_sync: MagicMock, mock_kb_repo: Path, mock_project_repo: Path
    ) -> None:
        """run_full_analysis does not call sync (sync is a CLI concern)."""
        with patch("brain.config.load_config", return_value={"local_path": str(mock_kb_repo)}):
            try:
                analysis.run_full_analysis(mock_project_repo)
            except Exception:
                pass  # may fail due to missing git state; sync not being called is what matters

        mock_sync.assert_not_called()

    @patch("brain.operations.sync.sync_knowledge_base")
    @patch("brain.storage")
    def test_analyze_succeeds_with_mocks(
        self,
        mock_storage: MagicMock,
        mock_sync: MagicMock,
        mock_kb_repo: Path,
        mock_project_repo: Path,
    ) -> None:
        """run_full_analysis succeeds when storage is mocked."""
        project_kb_path = mock_kb_repo / "test" / "project"
        project_kb_path.mkdir(parents=True, exist_ok=True)

        mock_storage.ensure_project_kb_path.return_value = project_kb_path
        mock_storage.load_project_metadata.return_value = None

        with patch("brain.config.load_config", return_value={"local_path": str(mock_kb_repo)}):
            (mock_project_repo / "test.py").write_text("# Test\n")
            subprocess.run(
                ["git", "add", "test.py"], cwd=mock_project_repo, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Add test"],
                cwd=mock_project_repo,
                check=True,
                capture_output=True,
            )

            result = analysis.run_full_analysis(mock_project_repo)

        assert result["success"] is True
        mock_sync.assert_not_called()  # sync is a CLI concern, not in run_full_analysis


class TestAnalyzeIncremental:
    """End-to-end incremental analysis against real git repositories."""

    def test_deleted_source_removes_rag_chunks(
        self, mock_kb_repo: Path, mock_project_repo: Path
    ) -> None:
        """Deleting a source file removes its chunks from the RAG index."""
        from brain.rag.index import RagIndex

        src = mock_project_repo / "mod.py"
        src.write_text('"""Module mod."""\n\ndef f():\n    pass\n')
        subprocess.run(
            ["git", "add", "mod.py"], cwd=mock_project_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "add mod"],
            cwd=mock_project_repo,
            check=True,
            capture_output=True,
        )

        with patch("brain.config.load_config", return_value={"local_path": str(mock_kb_repo)}):
            # First (full) analysis writes RAG chunks.
            result1 = analysis.run_full_analysis(mock_project_repo)
            assert result1["success"] is True
            assert result1["files_analyzed"] >= 1

            # Verify chunks exist for the file
            rag_dir = mock_kb_repo / "test" / "project" / ".rag"
            index = RagIndex.open(rag_dir / "index.sqlite3")
            try:
                manifest = index.file_manifest("mod.py")
                assert len(manifest) > 0
            finally:
                index.close()

            # Delete and commit, then re-analyze incrementally.
            subprocess.run(
                ["git", "rm", "mod.py"],
                cwd=mock_project_repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "rm mod"],
                cwd=mock_project_repo,
                check=True,
                capture_output=True,
            )
            result2 = analysis.run_full_analysis(mock_project_repo)

        assert result2["success"] is True
        assert result2["deleted"] == 1

        # Verify chunks are removed from the index
        index = RagIndex.open(rag_dir / "index.sqlite3")
        try:
            manifest = index.file_manifest("mod.py")
            assert len(manifest) == 0
        finally:
            index.close()
