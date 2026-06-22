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
        assert "lines_of_code" in frontmatter
        # last_analyzed is intentionally absent: it made markdown non-deterministic
        assert "last_analyzed" not in frontmatter

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


def test_reanalysis_is_deterministic():
    """Re-analyzing unchanged source yields byte-identical markdown (no churn)."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = project_root / "kb"
        kb_path.mkdir()

        test_file = project_root / "m.py"
        test_file.write_text('"""Module m."""\n\ndef f() -> int:\n    return 1\n')

        analyzer.analyze_file(test_file, kb_path, project_root)
        first = (kb_path / "m.md").read_text()

        analyzer.analyze_file(test_file, kb_path, project_root)
        second = (kb_path / "m.md").read_text()

        assert first == second
        assert "last_analyzed" not in first

        # A real change to the documented surface must still be written.
        test_file.write_text('"""Module m, revised."""\n\ndef f() -> int:\n    return 1\n')
        analyzer.analyze_file(test_file, kb_path, project_root)
        third = (kb_path / "m.md").read_text()

        assert third != second
        assert "Module m, revised." in third


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
    """tree-sitter 容错解析——不完整代码不会崩溃，能提取到什么就产出什么。"""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        # 不完整的 Python 代码（ast 会抛 SyntaxError）
        test_file = project_root / "broken.py"
        test_file.write_text("def broken(\n")

        # 不应抛异常——tree-sitter 容错
        analyzer.analyze_file(test_file, kb_path, project_root)

        # tree-sitter 会尽量解析，可能产出最小 markdown
        # 也可能因为符号名为空而跳过——两种行为都可以接受
        output = kb_path / "broken.md"
        if output.exists():
            content = output.read_text()
            # 即使有输出，签名应反映不完整代码的状态
            assert "brain_schema" in content


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
    from brain.lang_config import get_config
    from brain.tree_sitter_utils import get_parser

    cfg = get_config("python")
    src = code.encode("utf-8")
    root = get_parser("python").parse(src).root_node
    symbols = analyzer._extract_symbols(root, src, code, cfg)

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

    from brain.markdown_renderer import _infer_tags

    # 测试文件路径
    path = Path("tests/test_module.py")
    symbols: dict = {"functions": [], "classes": []}
    tags = _infer_tags(path, symbols, "python")
    assert "python" in tags
    assert "test" in tags

    # 核心模块
    path = Path("src/brain/operations.py")
    tags = _infer_tags(path, symbols, "python")
    assert "python" in tags
    assert "core" in tags

    # 异步函数
    path = Path("src/module.py")
    symbols = {
        "functions": [{"name": "async_func", "is_async": True}],
        "classes": [],
    }
    tags = _infer_tags(path, symbols, "python")
    assert "async" in tags


# ======================================================================
# 多语言分析测试
# ======================================================================

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_analyze_go_file():
    """验证 Go 文件分析产出正确的 frontmatter。"""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        go_file = project_root / "sample.go"
        go_file.write_text(
            """package main

import "fmt"

// ComputeSum 计算总和。
func ComputeSum(values []int) int {
    total := 0
    for _, v := range values {
        total += v
    }
    return total
}
"""
        )

        analyzer.analyze_file(go_file, kb_path, project_root)

        output = kb_path / "sample.md"
        assert output.exists()
        content = output.read_text()

        assert "type: go-module" in content
        assert 'source_path: sample.go' in content
        assert "tags: [go]" in content
        assert "ComputeSum" in content


def test_analyze_javascript_file():
    """验证 JavaScript 文件分析产出正确的 frontmatter。"""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        js_file = project_root / "sample.js"
        js_file.write_text(
            """/** Sample module. */

/**
 * Compute sum.
 */
export function computeSum(values) {
    return values.reduce((a, b) => a + b, 0);
}
"""
        )

        analyzer.analyze_file(js_file, kb_path, project_root)

        output = kb_path / "sample.md"
        assert output.exists()
        content = output.read_text()

        assert "type: javascript-module" in content
        assert "tags: [javascript]" in content
        assert "computeSum" in content


def test_analyze_typescript_file():
    """验证 TypeScript 文件分析产出正确的 frontmatter。"""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        ts_file = project_root / "sample.ts"
        ts_file.write_text(
            """/** Sample module. */

/**
 * Compute sum.
 */
export function computeSum(values: number[]): number {
    return values.reduce((a, b) => a + b, 0);
}
"""
        )

        analyzer.analyze_file(ts_file, kb_path, project_root)

        output = kb_path / "sample.md"
        assert output.exists()
        content = output.read_text()

        assert "type: typescript-module" in content
        assert "tags: [typescript]" in content
        assert "computeSum" in content


def test_analyze_rust_file():
    """验证 Rust 文件分析产出正确的 frontmatter。"""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        rs_file = project_root / "sample.rs"
        rs_file.write_text(
            """//! Sample module.

/// 计算总和。
pub fn compute_sum(values: &[i32]) -> i32 {
    values.iter().sum()
}
"""
        )

        analyzer.analyze_file(rs_file, kb_path, project_root)

        output = kb_path / "sample.md"
        assert output.exists()
        content = output.read_text()

        assert "type: rust-module" in content
        assert "tags: [rust]" in content
        assert "compute_sum" in content


def test_multi_language_tags():
    """验证不同语言产生各自的标签。"""
    from brain.markdown_renderer import _infer_tags

    path = Path("src/module.py")
    symbols: dict = {"functions": [], "classes": []}

    assert "python" in _infer_tags(path, symbols, "python")
    assert "go" in _infer_tags(path, symbols, "go")
    assert "javascript" in _infer_tags(path, symbols, "javascript")
    assert "typescript" in _infer_tags(path, symbols, "typescript")
    assert "rust" in _infer_tags(path, symbols, "rust")
    assert "java" in _infer_tags(path, symbols, "java")


def test_analyze_java_file():
    """验证 Java 文件分析产出正确的 frontmatter。"""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        kb_path = Path(tmpdir) / "kb"
        kb_path.mkdir()

        java_file = project_root / "Repository.java"
        java_file.write_text(
            """package com.example;

import java.util.List;

/**
 * Sample Repository.
 */
public class Repository {
    private String root;

    public Repository(String root) {
        this.root = root;
    }

    public byte[] load(String key) {
        return null;
    }
}
"""
        )

        analyzer.analyze_file(java_file, kb_path, project_root)

        output = kb_path / "Repository.md"
        assert output.exists()
        content = output.read_text()

        assert "type: java-module" in content
        assert "tags: [java]" in content
        assert "Repository" in content
        # 类内方法应该出现
        assert "load" in content


