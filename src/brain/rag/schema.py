"""语言无关的代码 RAG chunk schema。

每个代码符号一条记录。``content`` 存储真实源码供 LLM 上下文使用。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Chunk:
    """单个可检索代码单元及其结构化元数据。"""

    chunk_id: str  # 稳定 id，索引内唯一
    file_path: str  # 仓库相对路径，posix 格式
    language: str  # 如 "python"
    chunk_type: str  # "module" / "function" / "class" / "method"
    symbol: str  # 叶子名（如 "analyze_file"）
    qualified_name: str  # 文件内作用域路径（如 "Foo.method"）
    parent_class: str | None  # 所属类名（G2 "所属类"），无则为 None
    start_line: int  # 1-indexed，含装饰器
    end_line: int  # 1-indexed，完整 span，永不被截断
    imports: tuple[str, ...]  # 模块级 import 列表
    signature: str  # 装饰器 + def/class 头部，空白已压缩
    docstring: str | None
    content: str  # 符号的源码体
    content_hash: str  # sha256(content) — G4 增量更新 key

    def to_row(self) -> dict[str, Any]:
        """展平为 SQLite 行（imports 以换行符连接）。"""
        return {
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
            "language": self.language,
            "chunk_type": self.chunk_type,
            "symbol": self.symbol,
            "qualified_name": self.qualified_name,
            "parent_class": self.parent_class or "",
            "start_line": self.start_line,
            "end_line": self.end_line,
            "imports": "\n".join(self.imports),
            "signature": self.signature,
            "docstring": self.docstring or "",
            "content": self.content,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Chunk:
        """从 :meth:`to_row` 产出的 SQLite 行重建 Chunk。"""
        imports_raw = row["imports"] or ""
        return cls(
            chunk_id=row["chunk_id"],
            file_path=row["file_path"],
            language=row["language"],
            chunk_type=row["chunk_type"],
            symbol=row["symbol"],
            qualified_name=row["qualified_name"],
            parent_class=row["parent_class"] or None,
            start_line=int(row["start_line"]),
            end_line=int(row["end_line"]),
            imports=tuple(imports_raw.split("\n")) if imports_raw else (),
            signature=row["signature"],
            docstring=row["docstring"] or None,
            content=row["content"],
            content_hash=row["content_hash"],
        )


def compute_content_hash(content: str) -> str:
    """chunk 内容的 SHA256 十六进制 — 增量重建 key（G4）。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def base_chunk_id(file_path: str, qualified_name: str) -> str:
    """基础 chunk id；冲突时 chunker 追加 ``:start_line``。"""
    suffix = qualified_name or "<module>"
    return f"{file_path}::{suffix}"
