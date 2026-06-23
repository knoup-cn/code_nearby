"""代码领域同义词扩展——查询增强。

三层 fallback 架构：

1. 用户自定义 dict (YAML) — 精确，权威
2. 内置 cluster (33组) — 零成本，覆盖广
3. embed 模型 (paraphrase-MiniLM-L3) — 开放词汇，自动发现 (opt-in, ``fastembed>=0.4``)

用于在 BM25 检索前扩展用户查询，使 "fetch" 也能命中包含 "get"/"retrieve"/"load" 的 chunk。

Usage::

    from code_nearby.rag.synonyms import expand_query
    expanded = expand_query("fetch user data")  # → "fetch user data get retrieve load"
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

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


def expand_query(
    query: str,
    custom_synonyms: dict[str, list[str]] | None = None,
    max_expansions: int = 3,
    enable_embed: bool = False,
    _trace: list[dict] | None = None,
) -> str:
    """为查询添加代码领域同义词，扩展 BM25 命中范围。

    三层 fallback（按优先级）：
    1. 用户自定义 dict (custom_synonyms) — 精确，权威
    2. 内置 static cluster — 零成本，覆盖广
    3. embed 模型兜底 — 开放词汇，自动发现 (opt-in)

    ``max_expansions`` 控制**全局**最大新增词数（约为 term 数 × max_expansions）。
    Layer 1 命中时注入全部自定义同义词；Layer 2/3 注入不超过 max_expansions 个。
    已是查询中出现的词不会被重复添加。

    Args:
        query: 原始查询字符串。
        custom_synonyms: 用户自定义同义词 dict，格式 ``{term: [syn1, syn2, ...]}``。
        max_expansions: 控制全局最大新增词数。
        enable_embed: 启用 embed 模型兜底（需 ``fastembed>=0.4``）。
        _trace: 传入一个空 list，调用后会被填入每层的命中详情::

            [{"term": "middleware", "layer": "embed",
              "synonyms": ["handler", "interceptor"], "scores": [0.82, 0.78]},
             {"term": "auth", "layer": "custom", "synonyms": ["sso", "kerberos"]},
             {"term": "fetch", "layer": "cluster",
              "synonyms": ["get", "retrieve", "load"]}]

    Returns:
        扩展后的查询字符串（可能等于原查询）。
    """
    terms = query.lower().split()
    seen: set[str] = set(terms)
    added: list[str] = []

    for term in terms:
        # ── Layer 1: 用户自定义 dict ──
        if custom_synonyms and term in custom_synonyms:
            hits: list[str] = []
            for syn in custom_synonyms[term]:
                if syn not in seen:
                    added.append(syn)
                    seen.add(syn)
                    hits.append(syn)
            if _trace is not None and hits:
                _trace.append({"term": term, "layer": "custom", "synonyms": hits})
            continue

        # ── Layer 2: 内置静态 cluster ──
        syns = _SYNONYM_LOOKUP.get(term)
        if syns:
            hits = []
            for s in syns:
                if s != term and s not in seen:
                    added.append(s)
                    seen.add(s)
                    hits.append(s)
                    if len(added) >= max_expansions * len(terms):
                        break
            if _trace is not None and hits:
                _trace.append({"term": term, "layer": "cluster", "synonyms": hits})
            continue

        # ── Layer 3: embed 兜底 (opt-in) ──
        if enable_embed:
            vocab = _build_vocab()
            candidates = [w for w in vocab if w not in seen]
            embed_hits = _expand_with_embed(term, candidates, top_k=max_expansions)
            hits = []
            hit_scores: list[float] = []
            for s, score in embed_hits:
                if s not in seen:
                    added.append(s)
                    seen.add(s)
                    hits.append(s)
                    hit_scores.append(round(score, 4))
            if _trace is not None and hits:
                _trace.append(
                    {"term": term, "layer": "embed", "synonyms": hits, "scores": hit_scores}
                )

        if len(added) >= max_expansions * len(terms):
            break

    if not added:
        return query
    return f"{query} {' '.join(added)}"


# ═══════════════════════════════════════════════════════════════
# Embed 兜底层 (opt-in, fastembed>=0.4)
# ═══════════════════════════════════════════════════════════════

_embed_model = None  # 懒加载单例


def _get_embed_model() -> Any:
    """延迟加载 fastembed 模型。首次调用下载 ~35MB，缓存于 HuggingFace cache。

    Returns:
        TextEmbedding 实例，或 ``None`` (fastembed 未安装 / 加载失败)。
    """
    global _embed_model
    if _embed_model is None:
        try:
            from fastembed import TextEmbedding

            _embed_model = TextEmbedding("sentence-transformers/paraphrase-MiniLM-L3-v2")
        except (ImportError, OSError):
            return None
    return _embed_model


def is_embed_available() -> bool:
    """检查 fastembed 模型是否可用（不触发下载）。"""
    try:
        import fastembed  # noqa: F401

        return True
    except ImportError:
        return False


def _build_vocab() -> list[str]:
    """从内置 SYNONYM_CLUSTERS 抽取所有词汇作为 embed 检索候选 pool。"""
    seen: set[str] = set()
    vocab: list[str] = []
    for cluster in SYNONYM_CLUSTERS:
        for term in cluster:
            if term not in seen:
                vocab.append(term)
                seen.add(term)
    return vocab


def _expand_with_embed(
    term: str,
    candidates: list[str],
    threshold: float = 0.75,
    top_k: int = 3,
) -> list[tuple[str, float]]:
    """用 embed 模型在候选词中找到语义最近的同义词。

    Args:
        term: 查询词。
        candidates: 候选同义词列表。
        threshold: 余弦相似度阈值（≥ 此值才入选）。
        top_k: 最多返回的同义词数。

    Returns:
        ``[(同义词, 相似度), ...]`` 按相似度降序排列。模型不可用时返回空列表。
    """
    model = _get_embed_model()
    if model is None:
        return []

    import numpy as np

    term_vec = np.array(next(iter(model.embed([term]))))
    candidate_vecs = list(model.embed(candidates))

    scored: list[tuple[str, float]] = []
    for cand, cand_vec in zip(candidates, candidate_vecs, strict=True):
        sim = _cosine(term_vec, np.array(cand_vec))
        if sim >= threshold:
            scored.append((cand, sim))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度。"""
    import numpy as np

    dot = float(np.dot(a, b))
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ═══════════════════════════════════════════════════════════════
# 自定义同义词加载
# ═══════════════════════════════════════════════════════════════


def load_custom_synonyms(path: str | Path) -> dict[str, list[str]] | None:
    """从 YAML/JSON 文件加载用户自定义同义词。

    格式::

        auth: [sso, oauth2, kerberos]
        deploy: [release, ship, rollout]

    Args:
        path: YAML 或 JSON 文件路径。

    Returns:
        ``{term: [synonym, ...]}`` dict，或 ``None``（文件不存在 / 格式错误）。
    """
    import json

    try:
        import yaml
    except ImportError:
        yaml = None

    path = Path(path)
    if not path.exists():
        return None

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    # 尝试 YAML，失败则 JSON
    data: dict | None = None
    if yaml is not None:
        with contextlib.suppress(Exception):  # yaml.YAMLError 或 AttributeError
            data = yaml.safe_load(raw)

    if data is None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

    if not isinstance(data, dict):
        return None

    result: dict[str, list[str]] = {}
    for k, v in data.items():
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            result[str(k)] = [str(x) for x in v]

    return result if result else None
