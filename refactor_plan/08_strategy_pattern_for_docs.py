"""重构方案 8：引入文档生成策略模式（OCP - Open/Closed Principle）

当前问题：
- _generate_obsidian_md 硬编码 Markdown 格式
- 要支持其他格式（JSON、HTML、Notion）需要重写整个函数
- 违反开闭原则（对扩展不开放）

解决方案：采用策略模式，支持多种文档格式。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


# ============================================================
# 核心数据模型（格式无关）
# ============================================================


@dataclass
class FileMetadata:
    """文件元数据（格式无关）。"""
    module_name: str
    full_module_name: str
    source_path: str
    language: str
    lines_of_code: int
    module_docstring: str | None
    tags: list[str]


@dataclass
class FunctionInfo:
    """函数信息。"""
    name: str
    lineno: int
    end_lineno: int
    signature: str
    docstring: str | None
    args: list[str]
    return_type: str | None
    is_private: bool
    is_async: bool


@dataclass
class MethodInfo:
    """方法信息。"""
    name: str
    lineno: int
    end_lineno: int
    signature: str
    docstring: str | None
    args: list[str]
    return_type: str | None
    is_private: bool
    is_async: bool


@dataclass
class ClassInfo:
    """类信息。"""
    name: str
    lineno: int
    end_lineno: int
    signature: str
    docstring: str | None
    bases: list[str]
    methods: list[MethodInfo]
    is_private: bool


@dataclass
class DependencyInfo:
    """依赖信息。"""
    all_imports: list[str]
    internal_imports: list[str]
    external_imports: list[str]


@dataclass
class DocumentData:
    """完整的文档数据（格式无关）。"""
    relative_path: Path
    project_name: str
    metadata: FileMetadata
    functions: list[FunctionInfo]
    classes: list[ClassInfo]
    dependencies: DependencyInfo


# ============================================================
# 策略接口
# ============================================================


class DocumentRenderer(Protocol):
    """文档渲染器协议。

    每种格式实现自己的渲染器。
    """

    def render(self, data: DocumentData) -> str:
        """将文档数据渲染为目标格式。

        Args:
            data: 文档数据（格式无关）

        Returns:
            渲染后的文档内容
        """
        ...

    def file_extension(self) -> str:
        """返回文件扩展名（如 ".md", ".json", ".html"）。"""
        ...


# ============================================================
# 策略实现 1：Obsidian Markdown
# ============================================================


class ObsidianMarkdownRenderer:
    """Obsidian Markdown 渲染器。"""

    def render(self, data: DocumentData) -> str:
        """渲染为 Obsidian 兼容的 Markdown。"""
        sections = [
            self._render_frontmatter(data),
            "",
            self._render_header(data),
            "",
            self._render_public_api(data),
            "",
            self._render_classes(data),
            "",
            self._render_dependencies(data),
            "",
            self._render_footer(),
        ]

        return "\n".join(s for s in sections if s)

    def file_extension(self) -> str:
        return ".md"

    # --- 子渲染方法 ---

    def _render_frontmatter(self, data: DocumentData) -> str:
        """渲染 YAML frontmatter。"""
        lines = [
            "---",
            'brain_schema: "v1"',
            f'type: {data.metadata.language}-module',
            f'source_path: {data.metadata.source_path}',
            f'module: {data.metadata.full_module_name}',
        ]

        # Exports
        exports = [f.name for f in data.functions if not f.is_private]
        exports += [c.name for c in data.classes if not c.is_private]
        if exports:
            lines.append("exports:")
            for exp in exports:
                lines.append(f"  - {exp}")

        # Dependencies
        if data.dependencies.internal_imports:
            lines.append("dependencies:")
            for imp in data.dependencies.internal_imports:
                link_name = imp.split(".")[-1]
                lines.append(f'  - "[[{link_name}]]"')

        # Metrics
        lines.append(f'lines_of_code: {data.metadata.lines_of_code}')

        # Tags
        lines.append(f"tags: [{', '.join(data.metadata.tags)}]")

        lines.append("---")
        return "\n".join(lines)

    def _render_header(self, data: DocumentData) -> str:
        """渲染标题和模块说明。"""
        lines = [f"# {data.metadata.module_name}", ""]

        if data.metadata.module_docstring:
            lines.append("> [!info] Module Purpose")
            for line in data.metadata.module_docstring.split("\n"):
                lines.append(f"> {line}")
            lines.append("")

        return "\n".join(lines)

    def _render_public_api(self, data: DocumentData) -> str:
        """渲染公共 API。"""
        public_funcs = [f for f in data.functions if not f.is_private]
        if not public_funcs:
            return ""

        lines = ["## Public API", ""]

        for func in public_funcs:
            args_str = ", ".join(func.args)
            signature = f'{func.name}({args_str})'
            if func.return_type:
                signature += f' -> {func.return_type}'

            lines.append(f"### `{signature}`")
            lines.append("")
            lines.append(f'**Location**: `{data.relative_path}:{func.lineno}`')

            if func.is_async:
                lines.append("**Type**: Async function")

            lines.append("")

            if func.docstring:
                lines.append("> [!example] Documentation")
                for line in func.docstring.split("\n"):
                    lines.append(f"> {line}")
                lines.append("")

            lines.append("")

        return "\n".join(lines)

    def _render_classes(self, data: DocumentData) -> str:
        """渲染类。"""
        if not data.classes:
            return ""

        lines = ["## Classes", ""]

        for cls in data.classes:
            lines.append(f'### `{cls.name}`')
            lines.append("")
            lines.append(f'**Location**: `{data.relative_path}:{cls.lineno}`')

            if cls.bases:
                lines.append(f'**Inherits**: {", ".join(f"`{b}`" for b in cls.bases)}')

            lines.append("")

            if cls.docstring:
                lines.append("> [!info] Description")
                for line in cls.docstring.split("\n"):
                    lines.append(f"> {line}")
                lines.append("")

            # Methods
            public_methods = [m for m in cls.methods if not m.is_private]
            if public_methods:
                lines.append("**Public Methods**:")
                lines.append("")
                for method in public_methods:
                    args_str = ", ".join(method.args)
                    sig = f'{method.name}({args_str})'
                    if method.return_type:
                        sig += f' -> {method.return_type}'
                    lines.append(f"#### `{sig}`")
                    lines.append("")

            lines.append("")

        return "\n".join(lines)

    def _render_dependencies(self, data: DocumentData) -> str:
        """渲染依赖。"""
        if not data.dependencies.all_imports:
            return ""

        lines = ["## Dependencies", ""]

        if data.dependencies.internal_imports:
            lines.append("**Internal**:")
            for imp in data.dependencies.internal_imports:
                link_name = imp.split(".")[-1]
                lines.append(f"- [[{link_name}]]")
            lines.append("")

        if data.dependencies.external_imports:
            lines.append("**External**:")
            for imp in data.dependencies.external_imports:
                lines.append(f"- `{imp}`")
            lines.append("")

        return "\n".join(lines)

    def _render_footer(self) -> str:
        """渲染页脚。"""
        return "---\n\n**Navigation**: [[_PROJECT]] • [[_MODULES]]"


# ============================================================
# 策略实现 2：JSON
# ============================================================


import json


class JsonRenderer:
    """JSON 文档渲染器。"""

    def render(self, data: DocumentData) -> str:
        """渲染为 JSON 格式。"""
        doc = {
            "file": str(data.relative_path),
            "project": data.project_name,
            "metadata": {
                "module": data.metadata.full_module_name,
                "language": data.metadata.language,
                "lines_of_code": data.metadata.lines_of_code,
                "docstring": data.metadata.module_docstring,
                "tags": data.metadata.tags,
            },
            "functions": [
                {
                    "name": f.name,
                    "lineno": f.lineno,
                    "signature": f.signature,
                    "docstring": f.docstring,
                    "is_private": f.is_private,
                    "is_async": f.is_async,
                }
                for f in data.functions
            ],
            "classes": [
                {
                    "name": c.name,
                    "lineno": c.lineno,
                    "bases": c.bases,
                    "docstring": c.docstring,
                    "methods": [
                        {"name": m.name, "lineno": m.lineno}
                        for m in c.methods
                    ],
                }
                for c in data.classes
            ],
            "dependencies": {
                "internal": data.dependencies.internal_imports,
                "external": data.dependencies.external_imports,
            },
        }

        return json.dumps(doc, indent=2, ensure_ascii=False)

    def file_extension(self) -> str:
        return ".json"


# ============================================================
# 策略实现 3：HTML
# ============================================================


class HtmlRenderer:
    """HTML 文档渲染器。"""

    def render(self, data: DocumentData) -> str:
        """渲染为 HTML 格式。"""
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{data.metadata.module_name} - Documentation</title>
    <style>
        body {{ font-family: sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; border-bottom: 2px solid #eee; }}
        code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }}
        .function, .class {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
        .docstring {{ background: #f9f9f9; padding: 10px; margin: 10px 0; font-style: italic; }}
    </style>
</head>
<body>
    <h1>{data.metadata.module_name}</h1>
    <p><strong>Module:</strong> {data.metadata.full_module_name}</p>
    <p><strong>Lines of Code:</strong> {data.metadata.lines_of_code}</p>
"""

        # Functions
        if data.functions:
            html += "    <h2>Functions</h2>\n"
            for func in data.functions:
                if func.is_private:
                    continue
                html += f'    <div class="function">\n'
                html += f'        <h3><code>{func.name}({", ".join(func.args)})</code></h3>\n'
                if func.docstring:
                    html += f'        <div class="docstring">{func.docstring}</div>\n'
                html += f'        <p><em>Line {func.lineno}</em></p>\n'
                html += '    </div>\n'

        # Classes
        if data.classes:
            html += "    <h2>Classes</h2>\n"
            for cls in data.classes:
                html += f'    <div class="class">\n'
                html += f'        <h3><code>{cls.name}</code></h3>\n'
                if cls.docstring:
                    html += f'        <div class="docstring">{cls.docstring}</div>\n'
                html += '    </div>\n'

        html += """</body>
</html>"""

        return html

    def file_extension(self) -> str:
        return ".html"


# ============================================================
# 策略实现 4：Notion (示例)
# ============================================================


class NotionRenderer:
    """Notion 文档渲染器（简化示例）。"""

    def render(self, data: DocumentData) -> str:
        """渲染为 Notion API 格式（简化）。"""
        # Notion API 使用 block 结构
        blocks = {
            "object": "page",
            "properties": {
                "title": {"title": [{"text": {"content": data.metadata.module_name}}]},
                "Module": {"rich_text": [{"text": {"content": data.metadata.full_module_name}}]},
                "Language": {"select": {"name": data.metadata.language}},
            },
            "children": [],
        }

        # Add functions as blocks
        for func in data.functions:
            if func.is_private:
                continue
            blocks["children"].append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": func.name}}]},
            })

        return json.dumps(blocks, indent=2, ensure_ascii=False)

    def file_extension(self) -> str:
        return ".notion.json"


# ============================================================
# 渲染器工厂
# ============================================================


class RendererFactory:
    """文档渲染器工厂。"""

    _renderers: dict[str, type[DocumentRenderer]] = {
        "obsidian": ObsidianMarkdownRenderer,
        "json": JsonRenderer,
        "html": HtmlRenderer,
        "notion": NotionRenderer,
    }

    @classmethod
    def create(cls, format: str) -> DocumentRenderer:
        """创建渲染器实例。

        Args:
            format: 格式名称（obsidian, json, html, notion）

        Returns:
            渲染器实例

        Raises:
            ValueError: 如果格式不支持
        """
        renderer_class = cls._renderers.get(format.lower())
        if renderer_class is None:
            raise ValueError(f"Unsupported format: {format}")
        return renderer_class()

    @classmethod
    def register(cls, name: str, renderer_class: type[DocumentRenderer]):
        """注册自定义渲染器。

        Args:
            name: 格式名称
            renderer_class: 渲染器类
        """
        cls._renderers[name] = renderer_class

    @classmethod
    def list_formats(cls) -> list[str]:
        """列出支持的格式。"""
        return list(cls._renderers.keys())


# ============================================================
# 使用示例
# ============================================================


def generate_document(
    data: DocumentData,
    format: str = "obsidian",
) -> tuple[str, str]:
    """生成文档（支持多种格式）。

    Args:
        data: 文档数据
        format: 输出格式（obsidian, json, html, notion）

    Returns:
        (content, file_extension)
    """
    renderer = RendererFactory.create(format)
    content = renderer.render(data)
    extension = renderer.file_extension()
    return content, extension


def example_usage():
    """演示如何使用策略模式生成多种格式。"""
    # 准备文档数据（格式无关）
    data = DocumentData(
        relative_path=Path("src/brain/analyzer.py"),
        project_name="brain",
        metadata=FileMetadata(
            module_name="analyzer",
            full_module_name="brain.analyzer",
            source_path="src/brain/analyzer.py",
            language="python",
            lines_of_code=150,
            module_docstring="Code analysis module",
            tags=["python", "core"],
        ),
        functions=[
            FunctionInfo(
                name="analyze_file",
                lineno=30,
                end_lineno=73,
                signature="def analyze_file(file_path, kb_path, project_root):",
                docstring="Analyze a single file",
                args=["file_path", "kb_path", "project_root"],
                return_type="None",
                is_private=False,
                is_async=False,
            )
        ],
        classes=[],
        dependencies=DependencyInfo(
            all_imports=["pathlib", "tree_sitter", "brain.storage"],
            internal_imports=["brain.storage"],
            external_imports=["pathlib", "tree_sitter"],
        ),
    )

    # 生成多种格式
    for format_name in ["obsidian", "json", "html"]:
        content, ext = generate_document(data, format_name)
        output_file = f"analyzer{ext}"
        print(f"\n=== {format_name.upper()} ({output_file}) ===")
        print(content[:200] + "..." if len(content) > 200 else content)


def example_custom_renderer():
    """演示如何添加自定义渲染器。"""

    class PlainTextRenderer:
        """纯文本渲染器（自定义示例）。"""

        def render(self, data: DocumentData) -> str:
            lines = [
                f"Module: {data.metadata.full_module_name}",
                f"Language: {data.metadata.language}",
                f"Lines: {data.metadata.lines_of_code}",
                "",
                "Functions:",
            ]

            for func in data.functions:
                lines.append(f"  - {func.name} (line {func.lineno})")

            return "\n".join(lines)

        def file_extension(self) -> str:
            return ".txt"

    # 注册自定义渲染器
    RendererFactory.register("plaintext", PlainTextRenderer)

    # 使用自定义渲染器
    content, ext = generate_document(mock_data(), "plaintext")
    print(f"\n=== Custom Renderer (plaintext) ===\n{content}")


def mock_data() -> DocumentData:
    """创建 mock 数据。"""
    return DocumentData(
        relative_path=Path("test.py"),
        project_name="test",
        metadata=FileMetadata(
            module_name="test",
            full_module_name="test",
            source_path="test.py",
            language="python",
            lines_of_code=10,
            module_docstring="Test module",
            tags=["test"],
        ),
        functions=[],
        classes=[],
        dependencies=DependencyInfo([], [], []),
    )


# ============================================================
# 迁移计划
# ============================================================

MIGRATION_PLAN = """
# 文档生成策略模式迁移计划

## 当前状态

硬编码 Markdown 生成：
- _generate_obsidian_md() 硬编码格式
- 要支持新格式需要重写整个函数
- 违反开闭原则（OCP）

## 目标状态

策略模式：
- DocumentRenderer 协议（开放扩展）
- 多种渲染器实现（Obsidian, JSON, HTML, Notion）
- RendererFactory 工厂模式

## 迁移步骤

### 阶段 1：抽象数据模型

创建 `src/brain/document_model.py`：
```python
@dataclass
class DocumentData:
    relative_path: Path
    project_name: str
    metadata: FileMetadata
    functions: list[FunctionInfo]
    classes: list[ClassInfo]
    dependencies: DependencyInfo
```

### 阶段 2：实现 Obsidian 渲染器

将现有 _generate_obsidian_md 逻辑迁移到 ObsidianMarkdownRenderer：
```python
class ObsidianMarkdownRenderer:
    def render(self, data: DocumentData) -> str:
        # 现有逻辑
        ...
```

### 阶段 3：创建渲染器工厂

```python
renderer = RendererFactory.create("obsidian")
content = renderer.render(data)
```

### 阶段 4：添加新格式（无需修改现有代码）

```python
class JsonRenderer:
    def render(self, data: DocumentData) -> str:
        return json.dumps(...)

RendererFactory.register("json", JsonRenderer)
```

### 阶段 5：配置化（可选）

支持项目级配置：
```yaml
# brain.yaml
output_formats:
  - obsidian
  - json
  - html
```

### 阶段 6：向后兼容

保留旧函数，委托给新实现：
```python
def _generate_obsidian_md(...) -> str:
    data = _convert_to_document_data(...)
    renderer = ObsidianMarkdownRenderer()
    return renderer.render(data)
```

## 收益

1. **开闭原则**：添加新格式无需修改现有代码
2. **单一职责**：每个渲染器只负责一种格式
3. **可测试性**：每个渲染器可独立测试
4. **可扩展性**：用户可注册自定义渲染器
5. **灵活性**：运行时切换格式

## 使用示例

```python
# 生成 Obsidian Markdown（默认）
content, ext = generate_document(data, "obsidian")

# 生成 JSON（API 使用）
content, ext = generate_document(data, "json")

# 生成 HTML（Web 预览）
content, ext = generate_document(data, "html")

# 生成 Notion（导入到 Notion）
content, ext = generate_document(data, "notion")
```
"""


if __name__ == "__main__":
    print("文档生成策略模式")
    print("\n支持的格式:")
    for fmt in RendererFactory.list_formats():
        print(f"  - {fmt}")

    print("\n运行示例...")
    example_usage()
    example_custom_renderer()
