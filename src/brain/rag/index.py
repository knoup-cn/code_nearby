"""SQLite FTS5 index for code chunks (G9 + persistence + G4 manifest).

Stdlib ``sqlite3`` only — no vector DB, no external service. One ``.sqlite3``
file per project holds:

- ``chunks``      : canonical metadata + source content (source of truth, filters)
- ``chunks_fts``  : FTS5 BM25 over a tokenized blob (identifiers split so BM25
                    matches sub-tokens) — the primary lexical recall (C2)
- ``chunks_tri``  : FTS5 trigram over symbol/qualified-name for exact/substring
                    symbol matching
- ``meta``        : index-level key/value (schema version)

The ``chunks`` table doubles as the incremental manifest: per-file
``chunk_id -> content_hash`` lets the orchestrator skip unchanged chunks (G4).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from brain.rag.schema import Chunk

SCHEMA_VERSION = "1"

_DDL = """
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id      TEXT PRIMARY KEY,
  file_path     TEXT NOT NULL,
  language      TEXT NOT NULL,
  chunk_type    TEXT NOT NULL,
  symbol        TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  parent_class  TEXT NOT NULL DEFAULT '',
  start_line    INTEGER NOT NULL,
  end_line      INTEGER NOT NULL,
  imports       TEXT NOT NULL DEFAULT '',
  signature     TEXT NOT NULL DEFAULT '',
  docstring     TEXT NOT NULL DEFAULT '',
  content       TEXT NOT NULL,
  content_hash  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, blob);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_tri
  USING fts5(chunk_id UNINDEXED, sym, tokenize='trigram');
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_COLUMNS = (
    "chunk_id, file_path, language, chunk_type, symbol, qualified_name, "
    "parent_class, start_line, end_line, imports, signature, docstring, "
    "content, content_hash"
)

# split camelCase / PascalCase at case boundaries (zero-width)
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


class RagIndex:
    """Persistent FTS5-backed chunk index. Use :meth:`open` to construct."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, db_path: Path) -> RagIndex:
        """Open (creating if needed) the index at ``db_path``."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_DDL)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
        return cls(conn)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> RagIndex:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- writes ------------------------------------------------------------

    def upsert(self, chunks: Iterable[Chunk]) -> int:
        """Insert or replace chunks (and their FTS rows). Returns count."""
        count = 0
        with self._conn:  # transaction
            for chunk in chunks:
                self._delete_fts(chunk.chunk_id)
                row = chunk.to_row()
                self._conn.execute(
                    f"INSERT OR REPLACE INTO chunks ({_COLUMNS}) "
                    f"VALUES (:{', :'.join(_COLUMNS.split(', '))})",
                    row,
                )
                self._conn.execute(
                    "INSERT INTO chunks_fts(chunk_id, blob) VALUES (?, ?)",
                    (chunk.chunk_id, _search_blob(chunk)),
                )
                self._conn.execute(
                    "INSERT INTO chunks_tri(chunk_id, sym) VALUES (?, ?)",
                    (chunk.chunk_id, f"{chunk.symbol} {chunk.qualified_name}"),
                )
                count += 1
        return count

    def delete_chunks(self, chunk_ids: Iterable[str]) -> int:
        ids = list(chunk_ids)
        if not ids:
            return 0
        with self._conn:
            for chunk_id in ids:
                self._delete_fts(chunk_id)
                self._conn.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk_id,))
        return len(ids)

    def delete_file(self, file_path: str) -> int:
        """Delete all chunks belonging to a file. Returns count removed."""
        ids = [
            r["chunk_id"]
            for r in self._conn.execute(
                "SELECT chunk_id FROM chunks WHERE file_path = ?", (file_path,)
            )
        ]
        return self.delete_chunks(ids)

    def _delete_fts(self, chunk_id: str) -> None:
        self._conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
        self._conn.execute("DELETE FROM chunks_tri WHERE chunk_id = ?", (chunk_id,))

    # --- manifest / reads --------------------------------------------------

    def file_manifest(self, file_path: str) -> dict[str, str]:
        """Return ``{chunk_id: content_hash}`` for a file (incremental key)."""
        return {
            r["chunk_id"]: r["content_hash"]
            for r in self._conn.execute(
                "SELECT chunk_id, content_hash FROM chunks WHERE file_path = ?",
                (file_path,),
            )
        }

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        """Fetch full chunks by id, preserving the input order."""
        if not chunk_ids:
            return []
        placeholders = ",".join("?" * len(chunk_ids))
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM chunks WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        ).fetchall()
        by_id = {r["chunk_id"]: Chunk.from_row(dict(r)) for r in rows}
        return [by_id[cid] for cid in chunk_ids if cid in by_id]

    # --- queries -----------------------------------------------------------

    def query_bm25(
        self, text: str, limit: int, language: str | None = None, path_glob: str | None = None
    ) -> list[str]:
        """BM25 recall over the tokenized blob; best-first chunk ids (C2/C4)."""
        match = _fts_query(text)
        if match is None:
            return []
        return self._fts_search("chunks_fts", match, limit, language, path_glob)

    def query_symbol(
        self, text: str, limit: int, language: str | None = None, path_glob: str | None = None
    ) -> list[str]:
        """Trigram substring recall over symbol/qualified-name (C4-aware)."""
        needle = text.strip()
        if len(needle) < 3:  # trigram tokenizer needs >= 3 chars
            return []
        match = '"' + needle.replace('"', "") + '"'
        return self._fts_search("chunks_tri", match, limit, language, path_glob)

    def _fts_search(
        self, table: str, match: str, limit: int, language: str | None, path_glob: str | None
    ) -> list[str]:
        where = [f"{table} MATCH ?"]
        params: list[object] = [match]
        if language:
            where.append("c.language = ?")
            params.append(language)
        if path_glob:
            where.append("c.file_path GLOB ?")
            params.append(_normalize_glob(path_glob))
        params.append(limit)
        sql = (
            f"SELECT {table}.chunk_id AS chunk_id, bm25({table}) AS score "
            f"FROM {table} JOIN chunks AS c ON c.chunk_id = {table}.chunk_id "
            f"WHERE {' AND '.join(where)} ORDER BY score ASC LIMIT ?"
        )
        return [r["chunk_id"] for r in self._conn.execute(sql, params)]


# --- text helpers ----------------------------------------------------------


def _normalize_glob(pattern: str) -> str:
    """Map shell-style ``**`` onto SQLite GLOB semantics.

    SQLite ``GLOB`` has no ``**`` and its single ``*`` already spans ``/``. A
    recursive ``src/**/*.py`` must therefore collapse to ``src/*.py`` so it
    matches both ``src/a.py`` and ``src/sub/b.py``; left as-is the trailing
    ``/`` would exclude top-level files.
    """
    return pattern.replace("**/", "*").replace("**", "*")


def _search_blob(chunk: Chunk) -> str:
    """构建 BM25 检索文本 blob。

    包含：符号名 + 限定名 + imports + 签名 + docstring + 源码体 +
    camelCase/snake_case 分词扩展。imports 被加入以支持"搜 parser →
    命中所有 import parser 的 chunk"。
    """
    imports_text = " ".join(chunk.imports) if chunk.imports else ""
    base = "\n".join(
        [
            chunk.symbol,
            chunk.qualified_name,
            imports_text,
            chunk.signature,
            chunk.docstring or "",
            chunk.content,
        ]
    )
    extras = _split_identifiers(
        f"{chunk.symbol} {chunk.qualified_name} {imports_text} {chunk.content}"
    )
    return f"{base}\n{extras}" if extras else base


def _split_identifiers(text: str) -> str:
    """Emit camelCase sub-tokens so BM25 matches identifier fragments."""
    pieces: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9]*", text):
        parts = [p for p in _CAMEL.split(raw) if p]
        if len(parts) > 1:
            pieces.extend(parts)
    return " ".join(pieces)


def _terms(text: str) -> list[str]:
    """Query → unique lowercased terms (snake_case + camelCase split)."""
    out: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9_]+", text):
        for piece in re.split(r"_+", raw):
            if not piece:
                continue
            out.append(piece)
            out.extend(p for p in _CAMEL.split(piece) if p)
    seen: set[str] = set()
    result: list[str] = []
    for term in out:
        low = term.lower()
        if low and low not in seen:
            seen.add(low)
            result.append(low)
    return result


def _fts_query(text: str) -> str | None:
    """Build a safe FTS5 MATCH expression (OR of quoted terms)."""
    terms = _terms(text)
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in terms)
