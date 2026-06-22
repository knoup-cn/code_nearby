"""代码领域同义词扩展——零模型、零依赖的查询增强。

提供一份精选的代码常用动词/名词同义词映射。用于在 BM25 检索前扩展用户查询，
使 "fetch" 也能命中包含 "get"/"retrieve"/"load" 的 chunk。

Usage::

    from brain.rag.synonyms import expand_query
    expanded = expand_query("fetch user data")  # → "fetch user data get retrieve load"
"""

from __future__ import annotations

# 代码领域动作/概念的同义词聚类（精心挑选，非穷举）
SYNONYM_CLUSTERS: list[tuple[str, ...]] = [
    ("get", "fetch", "retrieve", "obtain", "read", "load", "query", "select"),
    ("create", "make", "build", "construct", "new", "init", "initialize", "generate"),
    ("delete", "remove", "destroy", "drop", "clear", "erase", "purge", "unlink"),
    ("update", "modify", "change", "edit", "alter", "mutate", "set", "patch"),
    ("save", "write", "store", "persist", "put", "commit", "push"),
    ("find", "search", "locate", "lookup", "discover", "scan"),
    ("send", "dispatch", "emit", "publish", "post", "fire", "trigger"),
    ("handle", "process", "manage", "deal", "serve", "respond"),
    ("check", "validate", "verify", "assert", "test", "ensure"),
    ("start", "begin", "launch", "boot", "open", "connect"),
    ("stop", "end", "close", "shutdown", "terminate", "disconnect"),
    ("convert", "transform", "parse", "serialize", "deserialize", "encode", "decode"),
    ("compute", "calculate", "evaluate", "resolve", "derive"),
    ("render", "display", "show", "draw", "paint", "format"),
    ("log", "debug", "trace", "print", "warn", "error"),
    ("configure", "setup", "prepare", "arrange", "provision"),
    ("merge", "combine", "join", "concat", "fuse", "aggregate"),
    ("split", "divide", "separate", "partition", "chunk"),
    ("copy", "clone", "duplicate", "replicate"),
    ("move", "transfer", "relocate", "migrate", "shift"),
    ("auth", "authenticate", "login", "signin", "sign_in"),
    ("user", "account", "profile", "identity"),
    ("file", "document", "blob", "asset", "attachment"),
    ("config", "setting", "option", "preference", "parameter", "env"),
    ("error", "exception", "failure", "fault", "bug"),
    ("api", "endpoint", "route", "handler", "controller"),
    ("db", "database", "datastore", "storage", "repository"),
    ("http", "request", "response", "client", "server"),
    ("cache", "buffer", "pool", "memoize"),
    ("async", "await", "coroutine", "future", "promise"),
    ("token", "credential", "secret", "key", "password"),
    ("analyze", "parse", "inspect", "examine", "extract"),
    ("index", "catalog", "register", "enumerate", "list"),
    ("sync", "synchronize", "replicate", "mirror", "push", "pull"),
]

# 构建查表：term → 同义词有序列表（cluster 顺序即优先级）
_SYNONYM_LOOKUP: dict[str, list[str]] = {}
for cluster in SYNONYM_CLUSTERS:
    syns = list(cluster)
    for term in cluster:
        _SYNONYM_LOOKUP[term] = syns


def expand_query(query: str, max_expansions: int = 3) -> str:
    """为查询添加代码领域同义词，扩展 BM25 命中范围。

    每个识别到的词最多添加 ``max_expansions`` 个同义词（按 cluster 原始顺序）。
    已是查询中出现的词不会被重复添加。

    Args:
        query: 原始查询字符串。
        max_expansions: 每个识别词最多添加的同义词数。

    Returns:
        扩展后的查询字符串（可能等于原查询）。
    """
    terms = query.lower().split()
    seen: set[str] = set(terms)
    added: list[str] = []

    for term in terms:
        syns = _SYNONYM_LOOKUP.get(term)
        if syns is None:
            continue
        count = 0
        for s in syns:
            if s != term and s not in seen:
                added.append(s)
                seen.add(s)
                count += 1
                if count >= max_expansions:
                    break

    if not added:
        return query
    return f"{query} {' '.join(added)}"
