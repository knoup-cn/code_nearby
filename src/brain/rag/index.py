"""SQLite FTS5 代码 chunk 索引。

仅用标准库 ``sqlite3``——无向量数据库、无外部服务。每个项目一个 ``.sqlite3`` 文件：

- ``chunks``      : 规范元数据 + 源码内容
- ``chunks_fts``  : FTS5 BM25 基于分词 blob（标识符拆分以支持子 token 匹配）
- ``chunks_tri``  : FTS5 trigram 基于 symbol/qualified-name 用于子串匹配
- ``meta``        : 索引级 key/value（schema 版本）

``chunks`` 表同时作为增量 manifest，通过 ``chunk_id → content_hash`` 实现。
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

# 在大小写边界拆分 camelCase / PascalCase（零宽断言）
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# CJK bigram 分词：Unicode 区块范围
_CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Ext A
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0x20000, 0x2A6DF),  # CJK Unified Ideographs Ext B
    (0x2F800, 0x2FA1F),  # CJK Compatibility Ideographs Supplement
)


def _is_cjk(ch: str) -> bool:
    """单字符是否在 CJK 范围内。"""
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _cjk_bigrams(text: str) -> list[str]:
    """从文本中提取 CJK 连续串，生成重叠 bigram。

    "获取用户数据" → ["获取", "取用", "用户", "户数", "数据"]
    单个 CJK 字符 → [字符本身]
    """
    result: list[str] = []
    chars: list[str] = []
    for ch in text:
        if _is_cjk(ch):
            chars.append(ch)
        else:
            if chars:
                if len(chars) == 1:
                    result.append(chars[0])
                else:
                    for i in range(len(chars) - 1):
                        result.append(chars[i] + chars[i + 1])
                chars = []
    if chars:
        if len(chars) == 1:
            result.append(chars[0])
        else:
            for i in range(len(chars) - 1):
                result.append(chars[i] + chars[i + 1])
    return result


class RagIndex:
    """基于 FTS5 的持久化 chunk 索引。使用 :meth:`open` 构造。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, db_path: Path) -> RagIndex:
        """打开（不存在则创建）位于 ``db_path`` 的索引。"""
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

    # --- 写入 ------------------------------------------------------------

    def upsert(self, chunks: Iterable[Chunk]) -> int:
        """插入或替换 chunk（及对应的 FTS 行）。返回写入数量。"""
        count = 0
        with self._conn:  # 事务
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
        """删除文件的所有 chunk。返回删除数量。"""
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

    # --- manifest / 读取 --------------------------------------------------

    def file_manifest(self, file_path: str) -> dict[str, str]:
        """返回文件的 ``{chunk_id: content_hash}``（增量更新 key）。"""
        return {
            r["chunk_id"]: r["content_hash"]
            for r in self._conn.execute(
                "SELECT chunk_id, content_hash FROM chunks WHERE file_path = ?",
                (file_path,),
            )
        }

    def list_files(self) -> list[str]:
        """返回索引中所有唯一文件路径。"""
        rows = self._conn.execute("SELECT DISTINCT file_path FROM chunks")
        return [r["file_path"] for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        """按 id 批量获取完整 chunk，保持输入顺序。"""
        if not chunk_ids:
            return []
        placeholders = ",".join("?" * len(chunk_ids))
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM chunks WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        ).fetchall()
        by_id = {r["chunk_id"]: Chunk.from_row(dict(r)) for r in rows}
        return [by_id[cid] for cid in chunk_ids if cid in by_id]

    # --- 查询 -----------------------------------------------------------

    def query_bm25(
        self, text: str, limit: int, language: str | None = None, path_glob: str | None = None
    ) -> list[str]:
        """基于分词 blob 的 BM25 召回；best-first chunk ids（C2/C4）。"""
        match = _fts_query(text)
        if match is None:
            return []
        return self._fts_search("chunks_fts", match, limit, language, path_glob)

    def query_symbol(
        self, text: str, limit: int, language: str | None = None, path_glob: str | None = None
    ) -> list[str]:
        """基于 symbol/qualified-name 的 trigram 子串召回。"""
        needle = text.strip()
        if len(needle) < 3:  # trigram tokenizer 需要 >= 3 个字符
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


# --- 文本辅助 ---------------------------------------------------------


def _normalize_glob(pattern: str) -> str:
    """将 shell 风格 ``**`` 映射到 SQLite GLOB 语义。

    SQLite ``GLOB`` 无 ``**``，其单个 ``*`` 已能跨 ``/`` 匹配。
    递归 ``src/**/*.py`` 需折叠为 ``src/*.py`` 才能同时匹配
    ``src/a.py`` 和 ``src/sub/b.py``。
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
    # CJK bigram 扩展（从 docstring + content 提取）
    cjk_source = f"{chunk.docstring or ''}\n{chunk.content}"
    cjk_extras = _cjk_bigrams(cjk_source)

    parts = [base]
    if extras:
        parts.append(extras)
    if cjk_extras:
        parts.append(" ".join(cjk_extras))
    return "\n".join(parts)


def _split_identifiers(text: str) -> str:
    """产出 camelCase 子 token，使 BM25 能匹配标识符片段。"""
    pieces: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9]*", text):
        parts = [p for p in _CAMEL.split(raw) if p]
        if len(parts) > 1:
            pieces.extend(parts)
    return " ".join(pieces)


def _terms(text: str) -> list[str]:
    """Query → 唯一小写词项（snake_case + camelCase + CJK bigram 拆分）。"""
    out: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9_]+", text):
        for piece in re.split(r"_+", raw):
            if not piece:
                continue
            out.append(piece)
            out.extend(p for p in _CAMEL.split(piece) if p)
    # CJK bigram 提取
    out.extend(_cjk_bigrams(text))
    seen: set[str] = set()
    result: list[str] = []
    for term in out:
        low = term.lower()
        if low and low not in seen:
            seen.add(low)
            result.append(low)
    return result


def _fts_query(text: str) -> str | None:
    """构建安全的 FTS5 MATCH 表达式（带引号词项的 OR）。"""
    terms = _terms(text)
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in terms)
