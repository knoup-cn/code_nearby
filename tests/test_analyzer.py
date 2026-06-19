"""Tests for analyzer module."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from brain import analyzer


def test_analyze_python_file():
    """Test basic Python file analysis."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # Create a test Python file
        test_file = project_root / "test_module.py"
        test_file.write_text(
            '''"""Test module docstring."""

def public_function(arg1: str, arg2: int) -> bool:
    """Public function docstring."""
    return True

def _private_function():
    """Private function."""
    pass

class TestClass:
    """Test class docstring."""

    def method(self):
        """Public method."""
        pass

    def _private_method(self):
        """Private method."""
        pass
'''
        )

        # Analyze the file
        analyzer.analyze_file(test_file, kb_path, project_root)

        # Check output exists
        output_file = kb_path / "test_module.md"
        assert output_file.exists()

        content = output_file.read_text()

        # Check frontmatter
        assert content.startswith("---")
        assert "brain_schema: \"v1\"" in content
        assert "type: python-module" in content
        assert "source_path: test_module.py" in content

        # Check exports (only public functions/classes)
        assert "- public_function" in content
        assert "- TestClass" in content

        # Check public API section
        assert "## Public API" in content
        assert "`public_function(arg1: str, arg2: int) -> bool`" in content
        assert "Public function docstring." in content

        # Check classes section
        assert "## Classes" in content
        assert "`TestClass`" in content
        assert "Test class docstring." in content
        assert "`method(self)`" in content

        # Check navigation
        assert "[[_PROJECT]]" in content
        assert "[[_MODULES]]" in content


def test_markdown_schema_v1():
    """Test that generated Markdown conforms to schema v1."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        test_file = project_root / "sample.py"
        test_file.write_text(
            '''"""Sample module."""

def func1(x: int) -> str:
    """Function 1."""
    return str(x)

class SampleClass:
    """Sample class."""
    pass
'''
        )

        analyzer.analyze_file(test_file, kb_path, project_root)

        content = (kb_path / "sample.md").read_text()
        fm_parts = content.split("---", 2)
        frontmatter = yaml.safe_load(fm_parts[1])

        # Check required fields
        assert frontmatter["brain_schema"] == "v1"
        assert frontmatter["type"] == "python-module"
        assert frontmatter["source_path"] == "sample.py"
        assert "module" in frontmatter
        assert "exports" in frontmatter
        assert "symbols" in frontmatter
        assert "last_analyzed" in frontmatter

        # Check symbols structure
        assert len(frontmatter["symbols"]) == 2  # func1 + SampleClass
        for sym in frontmatter["symbols"]:
            assert "name" in sym
            assert "type" in sym
            assert "signature" in sym
            assert "signature_hash" in sym
            assert "location_hint" in sym
            assert "is_private" in sym

        # Check signature_hash format (8 hex chars)
        for sym in frontmatter["symbols"]:
            assert len(sym["signature_hash"]) == 8
            assert all(c in "0123456789abcdef" for c in sym["signature_hash"])


def test_location_format():
    """Test that location is marked as hint in the body."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        test_file = project_root / "loc_test.py"
        test_file.write_text(
            '''def test_func():
    """Test."""
    pass
'''
        )

        analyzer.analyze_file(test_file, kb_path, project_root)
        content = (kb_path / "loc_test.md").read_text()

        # Check Location format includes (hint)
        assert "(hint)" in content
        assert "**Location**:" in content


def test_analyze_file_with_internal_dependencies():
    """Test analysis of file with internal imports."""
    with TemporaryDirectory() as tmpdir:
        # Create a project directory named 'brain' to match imports
        project_root = Path(tmpdir) / "brain"
        project_root.mkdir()
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # Create a test Python file with imports
        test_file = project_root / "operations.py"
        test_file.write_text(
            '''"""Operations module."""

from brain import analyzer, storage
from brain.git_utils import get_remote_url

def do_something():
    """Do something."""
    pass
'''
        )

        # Analyze the file
        analyzer.analyze_file(test_file, kb_path, project_root)

        content = (kb_path / "operations.md").read_text()

        # Check internal dependencies are wikilinks
        assert "## Dependencies" in content
        assert "**Internal**:" in content
        assert "[[analyzer]]" in content
        assert "[[git_utils]]" in content
        assert "[[storage]]" in content


def test_analyze_file_with_custom_project_name():
    """Test that internal import detection works with any project name."""
    with TemporaryDirectory() as tmpdir:
        # Create a project directory with a custom name
        project_root = Path(tmpdir) / "myproject"
        project_root.mkdir()
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # Create a test Python file with imports matching the project name
        test_file = project_root / "main.py"
        test_file.write_text(
            '''"""Main module."""

import myproject.utils
from myproject import config, helpers
import requests

def main():
    """Main function."""
    pass
'''
        )

        # Analyze the file
        analyzer.analyze_file(test_file, kb_path, project_root)

        content = (kb_path / "main.md").read_text()

        # Check internal dependencies are wikilinks
        assert "## Dependencies" in content
        assert "**Internal**:" in content
        assert "[[utils]]" in content
        assert "[[config]]" in content
        assert "[[helpers]]" in content

        # Check external dependency is code formatted
        assert "**External**:" in content
        assert "`requests`" in content


def test_analyze_file_skips_non_python():
    """Test that non-Python files are skipped."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # Create a non-Python file
        test_file = project_root / "README.md"
        test_file.write_text("# README")

        # Analyze should skip it
        analyzer.analyze_file(test_file, kb_path, project_root)

        # No output should be created
        assert not (kb_path / "README.md").exists()


def test_analyze_file_handles_syntax_error():
    """Test that files with syntax errors are skipped gracefully."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # Create a Python file with syntax error
        test_file = project_root / "broken.py"
        test_file.write_text("def broken(\n")

        # Should not raise exception
        analyzer.analyze_file(test_file, kb_path, project_root)

        # No output should be created
        assert not (kb_path / "broken.md").exists()


def test_extract_symbols():
    """Test symbol extraction."""
    code = '''
def func1():
    pass

async def async_func():
    pass

class MyClass:
    def method(self):
        pass
'''
    tree = __import__("ast").parse(code)
    symbols = analyzer._extract_symbols(tree, code)

    assert len(symbols["functions"]) == 2
    assert symbols["functions"][0]["name"] == "func1"
    assert symbols["functions"][0]["is_async"] is False
    assert "signature" in symbols["functions"][0]
    assert "signature_hash" in symbols["functions"][0]
    assert symbols["functions"][1]["name"] == "async_func"
    assert symbols["functions"][1]["is_async"] is True

    assert len(symbols["classes"]) == 1
    assert symbols["classes"][0]["name"] == "MyClass"
    assert len(symbols["classes"][0]["methods"]) == 1
    assert "signature" in symbols["classes"][0]
    assert "signature_hash" in symbols["classes"][0]


def test_infer_tags():
    """Test tag inference."""
    from pathlib import Path

    # Test file path
    path = Path("tests/test_module.py")
    symbols = {"functions": [], "classes": []}
    tags = analyzer._infer_tags(path, symbols)
    assert "python" in tags
    assert "test" in tags

    # Core module
    path = Path("src/brain/operations.py")
    tags = analyzer._infer_tags(path, symbols)
    assert "python" in tags
    assert "core" in tags

    # Async function
    path = Path("src/module.py")
    symbols = {
        "functions": [{"name": "async_func", "is_async": True}],
        "classes": []
    }
    tags = analyzer._infer_tags(path, symbols)
    assert "async" in tags
