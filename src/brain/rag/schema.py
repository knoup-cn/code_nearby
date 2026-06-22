"""Unified chunk schema for the code-RAG index (G2/G3).

One language-agnostic record per code symbol. Language differences are confined
to the chunker (tree-sitter grammars); storage and retrieval only ever see this
shape. ``content`` holds the symbol's real source body (fed to the LLM), unlike
the Goal-1 Markdown summaries which deliberately store signatures only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

# Chunk granularities. A file yields a "module" chunk (imports + docstring +
# top-level constants) plus one chunk per function / class / method.
CHUNK_TYPES = ("module", "function", "class", "method")


@dataclass(frozen=True, slots=True)
class Chunk:
    """A single retrievable code unit with its structural metadata."""

    chunk_id: str  # stable id, unique within an index
    file_path: str  # repo-relative, posix
    language: str  # e.g. "python"
    chunk_type: str  # one of CHUNK_TYPES
    symbol: str  # leaf name (e.g. "analyze_file")
    qualified_name: str  # in-file scope path (e.g. "Foo.method")
    parent_class: str | None  # enclosing class name, if any (G2 "所属类")
    start_line: int  # 1-indexed, inclusive (includes decorators)
    end_line: int  # 1-indexed, inclusive — full span, never truncated
    imports: tuple[str, ...]  # module-level imports in scope (file-scoped)
    signature: str  # decorators + def/class header, whitespace-collapsed
    docstring: str | None
    content: str  # source body of the symbol
    content_hash: str  # sha256(content) — G4 incremental key

    def to_row(self) -> dict[str, Any]:
        """Flatten to a SQLite-friendly row (imports joined by newline)."""
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
        """Rebuild a Chunk from a SQLite row produced by :meth:`to_row`."""
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
    """SHA256 hex of chunk content — the incremental-rebuild key (G4)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def base_chunk_id(file_path: str, qualified_name: str) -> str:
    """Base chunk id; the chunker appends ``:start_line`` on collision."""
    suffix = qualified_name or "<module>"
    return f"{file_path}::{suffix}"
