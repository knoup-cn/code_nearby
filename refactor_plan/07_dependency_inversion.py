"""重构方案 7：引入抽象层（DIP - Dependency Inversion Principle）

当前问题：
- analyzer.py 直接依赖 tree-sitter（紧耦合）
- operations.py 直接依赖 git_utils（紧耦合）
- 难以 mock 和测试
- 难以替换底层实现

解决方案：引入协议层，实现依赖反转。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Any


# ============================================================
# 核心抽象：解析器协议
# ============================================================


class ParseTree(Protocol):
    """抽象语法树（AST）协议。

    不依赖具体的 tree-sitter 实现。
    """

    def get_root(self) -> Any:
        """获取根节点。"""
        ...

    def query(self, pattern: str) -> list[Any]:
        """查询节点（类似 tree-sitter 的 query 语法）。"""
        ...


class SourceParser(Protocol):
    """源码解析器协议。

    解耦 analyzer 与具体的解析器实现（tree-sitter/Tree-sitter-ng/自定义）。
    """

    def parse(self, source: str, language: str) -> ParseTree:
        """解析源码为 AST。

        Args:
            source: 源码文本
            language: 语言标识（python, javascript, go 等）

        Returns:
            抽象语法树
        """
        ...

    def supports_language(self, language: str) -> bool:
        """检查是否支持指定语言。"""
        ...


# ============================================================
# Tree-sitter 适配器（默认实现）
# ============================================================


class TreeSitterAdapter:
    """Tree-sitter 解析器适配器（实现 SourceParser 协议）。"""

    def parse(self, source: str, language: str) -> ParseTree:
        """使用 tree-sitter 解析源码。"""
        from brain.tree_sitter_utils import get_parser

        src = source.encode("utf-8")
        tree = get_parser(language).parse(src)

        # 包装为 ParseTree（隐藏 tree-sitter 细节）
        return TreeSitterParseTree(tree)

    def supports_language(self, language: str) -> bool:
        """检查 tree-sitter 是否支持该语言。"""
        from brain.lang_config import detect_language

        try:
            # 简单检查：尝试获取 parser
            from brain.tree_sitter_utils import get_parser
            get_parser(language)
            return True
        except KeyError:
            return False


class TreeSitterParseTree:
    """Tree-sitter AST 包装器。"""

    def __init__(self, tree):
        self._tree = tree

    def get_root(self):
        """获取根节点（返回原始 tree-sitter 节点）。"""
        return self._tree.root_node

    def query(self, pattern: str) -> list[Any]:
        """执行 tree-sitter 查询。"""
        # 简化实现：返回所有匹配节点
        # 完整实现需要使用 tree-sitter 的 Query API
        raise NotImplementedError("Query not implemented in adapter")


# ============================================================
# 核心抽象：版本控制协议
# ============================================================


@dataclass
class FileChange:
    """文件变更信息。"""
    file_path: Path
    change_type: str  # "added" | "modified" | "deleted"


class VCS(Protocol):
    """版本控制系统协议。

    解耦 operations 与具体的 VCS 实现（git/svn/mercurial）。
    """

    def get_current_commit(self, repo_path: Path) -> str:
        """获取当前 commit hash。"""
        ...

    def get_changed_files(
        self, repo_path: Path, since: str | None = None
    ) -> list[FileChange]:
        """获取变更文件列表。

        Args:
            repo_path: 仓库路径
            since: 起始 commit（None 表示所有文件）

        Returns:
            变更文件列表
        """
        ...

    def get_tracked_files(self, repo_path: Path) -> list[Path]:
        """获取所有被追踪的文件。"""
        ...

    def is_repository(self, path: Path) -> bool:
        """检查路径是否为仓库。"""
        ...


# ============================================================
# Git 适配器（默认实现）
# ============================================================


class GitAdapter:
    """Git VCS 适配器（实现 VCS 协议）。"""

    def get_current_commit(self, repo_path: Path) -> str:
        """获取当前 commit hash。"""
        from brain import git_utils

        return git_utils.require_current_commit(repo_path)

    def get_changed_files(
        self, repo_path: Path, since: str | None = None
    ) -> list[FileChange]:
        """获取变更文件。"""
        from brain import git_utils

        if since is None:
            # 返回所有文件
            tracked = git_utils.get_tracked_files(repo_path)
            return [
                FileChange(file_path=f, change_type="added")
                for f in tracked
            ]

        # 增量变更
        changes = git_utils.get_changed_files(repo_path, since)

        result = []
        for change_type, file_list in changes.items():
            for file_path in file_list:
                result.append(
                    FileChange(file_path=file_path, change_type=change_type)
                )

        return result

    def get_tracked_files(self, repo_path: Path) -> list[Path]:
        """获取所有被追踪的文件。"""
        from brain import git_utils

        return git_utils.get_tracked_files(repo_path)

    def is_repository(self, path: Path) -> bool:
        """检查是否为 Git 仓库。"""
        from brain import git_utils

        return git_utils.is_git_repo(path)


# ============================================================
# 核心抽象：存储协议
# ============================================================


class Storage(Protocol):
    """知识库存储协议。

    解耦 analyzer 与具体的存储实现（文件系统/数据库/S3）。
    """

    def write_if_changed(self, path: Path, content: str) -> bool:
        """仅在内容变更时写入。

        Args:
            path: 相对路径
            content: 文件内容

        Returns:
            True if written, False if skipped
        """
        ...

    def read(self, path: Path) -> str | None:
        """读取文件内容。"""
        ...

    def exists(self, path: Path) -> bool:
        """检查文件是否存在。"""
        ...

    def delete(self, path: Path) -> bool:
        """删除文件。"""
        ...


# ============================================================
# 文件系统适配器（默认实现）
# ============================================================


class FileSystemStorage:
    """文件系统存储适配器。"""

    def __init__(self, root_path: Path):
        self.root_path = root_path

    def write_if_changed(self, path: Path, content: str) -> bool:
        """仅在内容变更时写入。"""
        full_path = self.root_path / path

        # 检查是否需要写入
        if full_path.exists() and full_path.read_text(encoding="utf-8") == content:
            return False

        # 确保目录存在
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        full_path.write_text(content, encoding="utf-8")
        return True

    def read(self, path: Path) -> str | None:
        """读取文件。"""
        full_path = self.root_path / path
        if not full_path.exists():
            return None
        return full_path.read_text(encoding="utf-8")

    def exists(self, path: Path) -> bool:
        """检查文件存在。"""
        return (self.root_path / path).exists()

    def delete(self, path: Path) -> bool:
        """删除文件。"""
        full_path = self.root_path / path
        if not full_path.exists():
            return False
        full_path.unlink()
        return True


# ============================================================
# 依赖注入容器
# ============================================================


class AnalysisContext:
    """分析上下文（依赖注入容器）。

    集中管理所有依赖，方便测试和替换实现。
    """

    def __init__(
        self,
        parser: SourceParser | None = None,
        vcs: VCS | None = None,
        storage: Storage | None = None,
    ):
        """初始化分析上下文。

        Args:
            parser: 源码解析器（默认：tree-sitter）
            vcs: 版本控制系统（默认：git）
            storage: 存储后端（默认：文件系统）
        """
        self.parser = parser or TreeSitterAdapter()
        self.vcs = vcs or GitAdapter()
        self.storage = storage or FileSystemStorage(Path.cwd())

    @staticmethod
    def create_default(kb_root: Path) -> AnalysisContext:
        """创建默认上下文（生产环境）。"""
        return AnalysisContext(
            parser=TreeSitterAdapter(),
            vcs=GitAdapter(),
            storage=FileSystemStorage(kb_root),
        )

    @staticmethod
    def create_for_testing() -> AnalysisContext:
        """创建测试上下文（mock 实现）。"""
        return AnalysisContext(
            parser=MockParser(),
            vcs=MockVCS(),
            storage=MockStorage(),
        )


# ============================================================
# Mock 实现（用于测试）
# ============================================================


class MockParser:
    """Mock 解析器（用于测试）。"""

    def __init__(self):
        self.parse_calls = []

    def parse(self, source: str, language: str) -> ParseTree:
        self.parse_calls.append((source, language))
        return MockParseTree()

    def supports_language(self, language: str) -> bool:
        return language in ["python", "javascript"]


class MockParseTree:
    """Mock AST。"""

    def get_root(self):
        return None

    def query(self, pattern: str):
        return []


class MockVCS:
    """Mock VCS（用于测试）。"""

    def __init__(self):
        self.files = [Path("test.py")]
        self.current_commit = "abc123"

    def get_current_commit(self, repo_path: Path) -> str:
        return self.current_commit

    def get_changed_files(self, repo_path: Path, since: str | None) -> list[FileChange]:
        return [FileChange(file_path=Path("test.py"), change_type="modified")]

    def get_tracked_files(self, repo_path: Path) -> list[Path]:
        return self.files

    def is_repository(self, path: Path) -> bool:
        return True


class MockStorage:
    """Mock 存储（用于测试）。"""

    def __init__(self):
        self.data: dict[Path, str] = {}

    def write_if_changed(self, path: Path, content: str) -> bool:
        old_content = self.data.get(path)
        if old_content == content:
            return False
        self.data[path] = content
        return True

    def read(self, path: Path) -> str | None:
        return self.data.get(path)

    def exists(self, path: Path) -> bool:
        return path in self.data

    def delete(self, path: Path) -> bool:
        if path in self.data:
            del self.data[path]
            return True
        return False


# ============================================================
# 重构后的 analyze_file（使用依赖注入）
# ============================================================


def analyze_file_with_context(
    file_path: Path,
    project_root: Path,
    context: AnalysisContext,
) -> bool:
    """分析单个文件（依赖注入版本）。

    Args:
        file_path: 待分析文件
        project_root: 项目根目录
        context: 分析上下文（包含所有依赖）

    Returns:
        True if file was written, False if skipped
    """
    from brain.lang_config import detect_language

    # 语言检测
    language = detect_language(file_path)
    if language is None:
        return False

    # 读取源码
    try:
        source = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False

    # 解析 AST（使用注入的 parser）
    tree = context.parser.parse(source, language)

    # 提取结构（这里简化了实际逻辑）
    # ... 使用 tree.get_root() 进行分析 ...

    # 生成文档
    relative_path = file_path.relative_to(project_root)
    md_content = f"# {relative_path.stem}\n\nAnalyzed content..."

    # 写入存储（使用注入的 storage）
    written = context.storage.write_if_changed(
        relative_path.with_suffix(".md"),
        md_content
    )

    return written


# ============================================================
# 测试示例
# ============================================================


def test_with_mocks():
    """演示如何使用 mock 测试。"""
    # 创建测试上下文
    context = AnalysisContext.create_for_testing()

    # 模拟分析
    file_path = Path("/tmp/test.py")
    project_root = Path("/tmp")

    # 注意：这里需要创建实际文件，或进一步 mock 文件系统
    # 这里仅演示 context 的使用

    # 验证 mock 被调用
    mock_parser = context.parser
    assert isinstance(mock_parser, MockParser)

    mock_storage = context.storage
    assert isinstance(mock_storage, MockStorage)

    print("✅ Mock testing works with dependency injection")


def test_with_real_implementations():
    """演示生产环境使用真实实现。"""
    kb_root = Path("/tmp/kb")
    context = AnalysisContext.create_default(kb_root)

    # 使用真实的 tree-sitter、git、文件系统
    assert isinstance(context.parser, TreeSitterAdapter)
    assert isinstance(context.vcs, GitAdapter)
    assert isinstance(context.storage, FileSystemStorage)

    print("✅ Production context uses real implementations")


# ============================================================
# 迁移计划
# ============================================================

MIGRATION_PLAN = """
# 依赖反转迁移计划

## 当前状态

直接依赖具体实现：
- analyzer.py → tree-sitter（紧耦合）
- operations.py → git_utils（紧耦合）
- analyzer.py → 文件系统（紧耦合）

## 目标状态

依赖抽象协议：
- analyzer.py → SourceParser 协议
- operations.py → VCS 协议
- analyzer.py → Storage 协议

## 迁移步骤

### 阶段 1：引入协议层（不破坏现有代码）

创建 `src/brain/protocols.py`：
```python
from typing import Protocol

class SourceParser(Protocol):
    def parse(self, source: str, language: str) -> ParseTree: ...

class VCS(Protocol):
    def get_current_commit(self, repo_path: Path) -> str: ...

class Storage(Protocol):
    def write_if_changed(self, path: Path, content: str) -> bool: ...
```

### 阶段 2：创建适配器

创建 `src/brain/adapters.py`：
```python
class TreeSitterAdapter:
    def parse(self, source: str, language: str) -> ParseTree:
        from brain.tree_sitter_utils import get_parser
        # ... 实现 ...

class GitAdapter:
    def get_current_commit(self, repo_path: Path) -> str:
        from brain import git_utils
        return git_utils.require_current_commit(repo_path)
```

### 阶段 3：引入依赖注入

创建 `AnalysisContext`：
```python
context = AnalysisContext.create_default(kb_root)
analyze_file_with_context(file_path, project_root, context)
```

### 阶段 4：逐步替换直接依赖

旧代码：
```python
from brain.tree_sitter_utils import get_parser
root = get_parser(language).parse(src).root_node
```

新代码：
```python
tree = context.parser.parse(source, language)
root = tree.get_root()
```

### 阶段 5：添加测试

```python
def test_analyze_with_mock():
    context = AnalysisContext.create_for_testing()
    result = analyze_file_with_context(file_path, project_root, context)
    assert result
    assert len(context.storage.data) == 1
```

## 收益

1. **可测试性**：轻松 mock 所有外部依赖
2. **可替换性**：可以替换 parser（如用 Rust 实现）
3. **可扩展性**：支持多种 VCS（git/svn/mercurial）
4. **解耦**：核心逻辑不依赖具体实现
5. **符合 SOLID**：满足依赖反转原则（DIP）

## 注意事项

1. **渐进迁移**：不要一次性替换所有代码
2. **保持兼容**：旧接口继续工作（委托给新实现）
3. **测试覆盖**：确保每个适配器都有测试
4. **性能考虑**：协议层不应增加显著开销
"""


if __name__ == "__main__":
    print("依赖反转重构方案")
    print("\n架构预览:")
    print("""
Before:
  analyzer.py ──> tree-sitter
  operations.py ──> git_utils
  analyzer.py ──> file system

After:
  analyzer.py ──> SourceParser (protocol)
                      ↑
                      |
                  TreeSitterAdapter

  operations.py ──> VCS (protocol)
                      ↑
                      |
                  GitAdapter

  analyzer.py ──> Storage (protocol)
                      ↑
                      |
                  FileSystemStorage
    """)
    print("\n优势:")
    print("- 依赖抽象而非具体实现")
    print("- 轻松 mock 和测试")
    print("- 可替换底层实现")
    print("- 符合 SOLID 的 DIP 原则")
    print("\n运行测试...")
    test_with_mocks()
    test_with_real_implementations()
