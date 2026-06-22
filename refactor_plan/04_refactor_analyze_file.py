"""重构方案 4：重构 analyze_file 为流水线

当前 analyze_file 承担 6 个职责，违反 SRP：
1. 文件 I/O
2. 语言检测
3. Tree-sitter 解析
4. 结构提取
5. Markdown 生成
6. 磁盘写入（含重复检测）

重构为清晰的流水线，每个阶段可独立测试和替换。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tree_sitter import Node


# ============================================================
# 阶段 1：数据模型（管道中流动的数据）
# ============================================================


@dataclass
class SourceFile:
    """源文件信息（阶段 1 输出）。"""
    file_path: Path
    relative_path: Path
    project_root: Path
    language: str
    source_text: str
    source_bytes: bytes
    ast_root: Node


@dataclass
class FileStructure:
    """文件结构信息（阶段 2 输出）。"""
    source_file: SourceFile
    metadata: dict[str, Any]
    symbols: dict[str, list[dict[str, Any]]]
    dependencies: dict[str, list[str]]


@dataclass
class Document:
    """生成的文档（阶段 3 输出）。"""
    file_path: Path
    relative_path: Path
    content: str
    format: str = "markdown"  # 支持未来扩展（json, html 等）


# ============================================================
# 阶段 2：协议（定义流水线接口）
# ============================================================


class SourceReader(Protocol):
    """源文件读取器。"""

    def read(self, file_path: Path, project_root: Path) -> SourceFile | None:
        """读取源文件并解析为 AST。

        Returns:
            SourceFile if successful, None if file cannot be processed
        """
        ...


class StructureExtractor(Protocol):
    """结构提取器。"""

    def extract(self, source: SourceFile) -> FileStructure:
        """从 AST 提取结构信息（元数据、符号、依赖）。"""
        ...


class DocumentGenerator(Protocol):
    """文档生成器。"""

    def generate(self, structure: FileStructure, project_name: str) -> Document:
        """从结构生成文档。"""
        ...


class DocumentWriter(Protocol):
    """文档写入器。"""

    def write(self, document: Document, kb_path: Path) -> bool:
        """将文档写入知识库。

        Returns:
            True if file was written, False if skipped (content unchanged)
        """
        ...


# ============================================================
# 阶段 3：默认实现（可替换的组件）
# ============================================================


class TreeSitterSourceReader:
    """基于 tree-sitter 的源文件读取器。"""

    def read(self, file_path: Path, project_root: Path) -> SourceFile | None:
        """读取并解析源文件。"""
        from brain.lang_config import detect_language
        from brain.tree_sitter_utils import get_parser

        # 语言检测
        language = detect_language(file_path)
        if language is None:
            return None

        # 读取文件
        try:
            source_text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return None

        # 解析 AST
        source_bytes = source_text.encode("utf-8")
        ast_root = get_parser(language).parse(source_bytes).root_node

        # 计算相对路径
        relative_path = file_path.relative_to(project_root)

        return SourceFile(
            file_path=file_path,
            relative_path=relative_path,
            project_root=project_root,
            language=language,
            source_text=source_text,
            source_bytes=source_bytes,
            ast_root=ast_root,
        )


class DefaultStructureExtractor:
    """默认结构提取器（使用现有逻辑）。"""

    def extract(self, source: SourceFile) -> FileStructure:
        """提取元数据、符号和依赖。"""
        from brain.analyzer import (
            _extract_dependencies,
            _extract_metadata,
            _extract_symbols,
        )
        from brain.lang_config import get_config

        cfg = get_config(source.language)

        # 提取各部分结构
        metadata = _extract_metadata(
            source.file_path,
            source.relative_path,
            source.ast_root,
            source.source_bytes,
            source.source_text,
            cfg,
        )

        symbols = _extract_symbols(
            source.ast_root,
            source.source_bytes,
            source.source_text,
            cfg,
        )

        project_name = source.project_root.resolve().name
        dependencies = _extract_dependencies(
            source.ast_root,
            source.source_bytes,
            project_name,
        )

        return FileStructure(
            source_file=source,
            metadata=metadata,
            symbols=symbols,
            dependencies=dependencies,
        )


class ObsidianDocumentGenerator:
    """Obsidian Markdown 文档生成器。"""

    def generate(self, structure: FileStructure, project_name: str) -> Document:
        """生成 Obsidian 兼容的 Markdown。"""
        from brain.analyzer import _generate_obsidian_md

        content = _generate_obsidian_md(
            file_path=structure.source_file.file_path,
            relative_path=structure.source_file.relative_path,
            metadata=structure.metadata,
            symbols=structure.symbols,
            dependencies=structure.dependencies,
            project_name=project_name,
        )

        return Document(
            file_path=structure.source_file.file_path,
            relative_path=structure.source_file.relative_path,
            content=content,
            format="markdown",
        )


class SmartDocumentWriter:
    """智能文档写入器（跳过未变更内容）。"""

    def write(self, document: Document, kb_path: Path) -> bool:
        """写入文档到知识库，内容相同时跳过。"""
        kb_file = kb_path / document.relative_path.with_suffix(".md")

        # 内容未变更时跳过写入（避免 git churn）
        if kb_file.exists() and kb_file.read_text(encoding="utf-8") == document.content:
            return False

        # 确保目录存在
        kb_file.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        kb_file.write_text(document.content, encoding="utf-8")
        return True


# ============================================================
# 阶段 4：流水线编排器
# ============================================================


class AnalysisPipeline:
    """文件分析流水线（可配置组件）。"""

    def __init__(
        self,
        reader: SourceReader | None = None,
        extractor: StructureExtractor | None = None,
        generator: DocumentGenerator | None = None,
        writer: DocumentWriter | None = None,
    ):
        """初始化流水线（使用依赖注入）。"""
        self.reader = reader or TreeSitterSourceReader()
        self.extractor = extractor or DefaultStructureExtractor()
        self.generator = generator or ObsidianDocumentGenerator()
        self.writer = writer or SmartDocumentWriter()

    def analyze_file(
        self, file_path: Path, kb_path: Path, project_root: Path
    ) -> bool:
        """分析单个文件并写入知识库（重构版）。

        Returns:
            True if file was written, False if skipped
        """
        project_name = project_root.resolve().name

        # 阶段 1：读取源文件
        source = self.reader.read(file_path, project_root)
        if source is None:
            return False

        # 阶段 2：提取结构
        structure = self.extractor.extract(source)

        # 阶段 3：生成文档
        document = self.generator.generate(structure, project_name)

        # 阶段 4：写入磁盘
        written = self.writer.write(document, kb_path)

        return written


# ============================================================
# 阶段 5：向后兼容的 API
# ============================================================


# 全局默认流水线实例
_default_pipeline = AnalysisPipeline()


def analyze_file(file_path: Path, kb_path: Path, project_root: Path) -> None:
    """分析单个文件并写入知识库（旧版 API，委托给流水线）。

    Args:
        file_path: 待分析文件
        kb_path: 知识库根路径
        project_root: 项目根目录（用于计算相对路径）
    """
    _default_pipeline.analyze_file(file_path, kb_path, project_root)


# ============================================================
# 阶段 6：测试和扩展示例
# ============================================================


def test_pipeline_isolation():
    """演示如何隔离测试每个阶段。"""
    from pathlib import Path
    import tempfile

    test_code = '''
def foo(x: int) -> str:
    """Test function."""
    return str(x)
'''

    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_code)
        temp_path = Path(f.name)

    project_root = temp_path.parent

    try:
        # 测试阶段 1：读取
        reader = TreeSitterSourceReader()
        source = reader.read(temp_path, project_root)
        assert source is not None
        assert source.language == "python"
        assert "def foo" in source.source_text

        # 测试阶段 2：提取
        extractor = DefaultStructureExtractor()
        structure = extractor.extract(source)
        assert len(structure.symbols["functions"]) == 1
        assert structure.symbols["functions"][0]["name"] == "foo"

        # 测试阶段 3：生成
        generator = ObsidianDocumentGenerator()
        document = generator.generate(structure, "test_project")
        assert "# " in document.content
        assert "foo" in document.content

        print("✅ Pipeline isolation test passed")

    finally:
        temp_path.unlink()


def example_custom_generator():
    """演示如何扩展：添加自定义文档格式。"""

    class JsonDocumentGenerator:
        """JSON 格式文档生成器（扩展示例）。"""

        def generate(self, structure: FileStructure, project_name: str) -> Document:
            """生成 JSON 格式文档。"""
            import json

            data = {
                "file": str(structure.source_file.relative_path),
                "language": structure.source_file.language,
                "metadata": structure.metadata,
                "symbols": structure.symbols,
                "dependencies": structure.dependencies,
            }

            content = json.dumps(data, indent=2, ensure_ascii=False)

            return Document(
                file_path=structure.source_file.file_path,
                relative_path=structure.source_file.relative_path,
                content=content,
                format="json",
            )

    # 使用自定义生成器
    pipeline = AnalysisPipeline(generator=JsonDocumentGenerator())
    # pipeline.analyze_file(...) 将生成 JSON 而非 Markdown


def example_mock_testing():
    """演示如何使用 mock 进行测试。"""

    class MockWriter:
        """Mock 写入器（用于测试）。"""

        def __init__(self):
            self.written_documents = []

        def write(self, document: Document, kb_path: Path) -> bool:
            self.written_documents.append(document)
            return True

    # 使用 mock 测试（无需实际文件系统）
    mock_writer = MockWriter()
    pipeline = AnalysisPipeline(writer=mock_writer)

    # pipeline.analyze_file(...) 会写入 mock_writer.written_documents
    # 测试时只需验证 mock_writer.written_documents 的内容


# ============================================================
# 迁移路径
# ============================================================

MIGRATION_PLAN = """
# 迁移步骤

## 阶段 1：引入流水线（不破坏现有代码）

在 analyzer.py 中添加：
```python
_default_pipeline = AnalysisPipeline()

def analyze_file(file_path, kb_path, project_root):
    # 旧实现委托给流水线
    _default_pipeline.analyze_file(file_path, kb_path, project_root)
```

## 阶段 2：逐步替换实现

将现有的 _extract_metadata、_extract_symbols 等函数
逐步迁移到流水线组件中。

## 阶段 3：测试覆盖

为每个组件编写独立的单元测试：
```python
def test_source_reader():
    reader = TreeSitterSourceReader()
    source = reader.read(test_file, project_root)
    assert source.language == "python"

def test_structure_extractor():
    extractor = DefaultStructureExtractor()
    structure = extractor.extract(mock_source)
    assert len(structure.symbols["functions"]) == 1
```

## 阶段 4：扩展新格式

添加新的文档格式无需修改核心代码：
```python
class NotionGenerator:
    def generate(self, structure, project_name):
        # 生成 Notion 格式
        ...

pipeline = AnalysisPipeline(generator=NotionGenerator())
```

## 收益

1. **可测试性**：每个阶段可独立测试，无需 mock 整个流程
2. **可扩展性**：添加新格式只需实现 DocumentGenerator 协议
3. **可替换性**：可以替换任意组件（如用 Rust parser 替换 tree-sitter）
4. **清晰性**：流程一目了然，降低认知负担
5. **依赖反转**：符合 SOLID 的 DIP 原则
"""

# ============================================================
# 主函数
# ============================================================

if __name__ == "__main__":
    print("Analyze File 流水线重构方案")
    print("\n架构预览:")
    print("""
SourceFile → FileStructure → Document → 磁盘
    ↑            ↑              ↑         ↑
    |            |              |         |
  Reader    Extractor      Generator   Writer
  (可替换)    (可替换)        (可替换)    (可替换)
    """)
    print("\n优势:")
    print("- 6 个职责 → 4 个独立组件")
    print("- 每个组件可单独测试")
    print("- 支持依赖注入和 mock")
    print("- 符合 SOLID 原则")
    print("- 易于扩展新格式")

    # 运行测试
    print("\n运行测试...")
    test_pipeline_isolation()
