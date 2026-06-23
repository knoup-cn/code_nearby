"""Tests for Source Fetch — disk-based source retrieval with window expansion."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from code_nearby.rag.source_fetch import (
    WINDOW_PRESETS,
    SourceSnippet,
    expand_window_params,
    fetch_source,
)


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a minimal project with a few source files."""
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "main.py").write_text(
        "import os\n"
        "import sys\n\n\n"
        "def greet(name: str) -> str:\n"
        '    """Return a greeting."""\n'
        '    return f"Hello, {name}!"\n\n\n'
        "def farewell(name: str) -> str:\n"
        '    """Say goodbye."""\n'
        '    return f"Goodbye, {name}!"\n',
    )
    (proj / "README.md").write_text("# Sample Project\n\nThis is a test.\n")
    return proj


# --- fetch_source: basic ---------------------------------------------------


def test_fetch_exact_lines(sample_project: Path) -> None:
    snippet = fetch_source(sample_project, "src/main.py", 5, 7)
    assert snippet is not None
    assert snippet.content == (
        'def greet(name: str) -> str:\n    """Return a greeting."""\n    return f"Hello, {name}!"'
    )
    assert snippet.start_line == 5
    assert snippet.end_line == 7
    assert snippet.original_start == 5
    assert snippet.original_end == 7


def test_fetch_single_line(sample_project: Path) -> None:
    snippet = fetch_source(sample_project, "src/main.py", 1, 1)
    assert snippet is not None
    assert snippet.content == "import os"
    assert snippet.start_line == 1
    assert snippet.end_line == 1


# --- fetch_source: window expansion ----------------------------------------


def test_fetch_with_context_before(sample_project: Path) -> None:
    snippet = fetch_source(sample_project, "src/main.py", 5, 5, context_before=2)
    assert snippet is not None
    assert snippet.start_line == 3  # 5 - 2
    assert snippet.original_start == 5
    assert "def greet" in snippet.content
    # line 2 ("import sys") 不在窗口内（窗口从 line 3 开始）


def test_fetch_with_context_after(sample_project: Path) -> None:
    snippet = fetch_source(sample_project, "src/main.py", 5, 5, context_after=2)
    assert snippet is not None
    assert snippet.end_line == 7  # 5 + 2
    assert snippet.original_end == 5
    assert 'return f"Hello' in snippet.content


def test_fetch_with_both_contexts(sample_project: Path) -> None:
    snippet = fetch_source(
        sample_project,
        "src/main.py",
        5,
        5,
        context_before=2,
        context_after=2,
    )
    assert snippet is not None
    assert snippet.start_line == 3
    assert snippet.end_line == 7
    assert snippet.original_start == 5
    assert snippet.original_end == 5


def test_window_clamped_to_file_start(sample_project: Path) -> None:
    snippet = fetch_source(sample_project, "src/main.py", 2, 3, context_before=10)
    assert snippet is not None
    assert snippet.start_line == 1  # clamped


def test_window_clamped_to_file_end(sample_project: Path) -> None:
    # file has 12 lines; request near the end with generous window
    snippet = fetch_source(sample_project, "src/main.py", 9, 9, context_after=20)
    assert snippet is not None
    assert snippet.end_line == 13  # clamped to actual file length (trailing \n adds 1)


# --- fetch_source: error handling ------------------------------------------


def test_file_not_found(sample_project: Path) -> None:
    assert fetch_source(sample_project, "nonexistent.py", 1, 5) is None


def test_permission_error_reads_as_none(sample_project: Path, monkeypatch) -> None:
    """Simulate an OSError during read by making Path.read_text raise."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "read_text", _raise)
    assert fetch_source(sample_project, "src/main.py", 1, 5) is None


def test_line_out_of_range_returns_empty_clamped(sample_project: Path) -> None:
    """Requesting lines beyond file end returns empty content (all lines past EOF)."""
    snippet = fetch_source(sample_project, "src/main.py", 100, 200)
    assert snippet is not None
    # start > total lines → empty result
    assert snippet.content == ""
    assert snippet.start_line == 100


# --- expand_window_params --------------------------------------------------


def test_window_preset_none() -> None:
    assert expand_window_params("none") == (0, 0)


def test_window_preset_minimal() -> None:
    assert expand_window_params("minimal") == (2, 2)


def test_window_preset_moderate() -> None:
    assert expand_window_params("moderate") == (5, 5)


def test_window_preset_generous() -> None:
    assert expand_window_params("generous") == (10, 10)


def test_window_case_insensitive() -> None:
    assert expand_window_params("NONE") == (0, 0)
    assert expand_window_params("Minimal") == (2, 2)


def test_window_custom_numeric() -> None:
    assert expand_window_params("3,7") == (3, 7)


def test_window_custom_with_spaces() -> None:
    assert expand_window_params(" 4 , 8 ") == (4, 8)


def test_window_invalid_custom_falls_back() -> None:
    assert expand_window_params("abc,def") == WINDOW_PRESETS["moderate"]


def test_window_unknown_falls_back() -> None:
    assert expand_window_params("gigantic") == WINDOW_PRESETS["moderate"]


# --- SourceSnippet dataclass -----------------------------------------------


def test_snippet_is_frozen() -> None:
    snippet = SourceSnippet(
        file_path="a.py",
        start_line=1,
        end_line=3,
        content="x",
        original_start=1,
        original_end=3,
    )
    with pytest.raises(FrozenInstanceError):
        snippet.start_line = 5  # type: ignore[misc]


def test_snippet_attributes(sample_project: Path) -> None:
    snippet = fetch_source(
        sample_project,
        "src/main.py",
        5,
        7,
        context_before=1,
        context_after=1,
    )
    assert snippet is not None
    assert snippet.file_path == "src/main.py"
    assert snippet.original_start == 5
    assert snippet.original_end == 7
    assert snippet.start_line <= snippet.original_start
    assert snippet.end_line >= snippet.original_end
