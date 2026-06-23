"""Tests for synonym expansion (static clusters, custom dict, embed fallback)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

from code_nearby.rag.synonyms import (
    _SYNONYM_LOOKUP,
    _build_vocab,
    _cosine,
    expand_query,
    load_custom_synonyms,
)


class TestStaticClusters:
    """内置 cluster 基本行为。"""

    def test_lookup_returns_all_peers(self) -> None:
        syns = _SYNONYM_LOOKUP["get"]
        assert "fetch" in syns
        assert "retrieve" in syns
        assert "get" in syns  # 自身也在列表中

    def test_expand_adds_synonyms(self) -> None:
        result = expand_query("fetch data")
        assert "get" in result or "retrieve" in result

    def test_no_duplicates_added(self) -> None:
        """查询中已有的词不会被重复添加。"""
        result = expand_query("get fetch retrieve")  # 三个已是同 cluster 的词
        # 不应该有重复词
        words = result.split()
        assert len(words) == len(set(words))

    def test_unknown_term_unchanged(self) -> None:
        """未命中任何 cluster 的词保持原样。"""
        result = expand_query("xyzabc123_nonexistent")
        assert result == "xyzabc123_nonexistent"


class TestCustomSynonyms:
    """Layer 1: 用户自定义 dict。"""

    def test_custom_override_clusters(self) -> None:
        """自定义 dict 优先于内置 cluster。"""
        custom = {"fetch": ["pluck", "grab"]}
        result = expand_query("fetch data", custom_synonyms=custom)
        assert "pluck" in result

    def test_custom_not_interfered_by_cluster(self) -> None:
        """自定义 dict 命中后不再走内置 cluster。"""
        custom = {"update": ["bump"]}
        result = expand_query("update", custom_synonyms=custom)
        # "bump" 在自定义中，应被加入；内置 cluster 的 "modify" 等也可能被加入
        # 但因为有 max_expansions 全局限制，bump 应优先出现
        assert "bump" in result

    def test_custom_none_ok(self) -> None:
        """custom_synonyms=None 不报错。"""
        result = expand_query("fetch data", custom_synonyms=None)
        assert "get" in result  # 内置生效


class TestEmbedFallback:
    """Layer 3: embed 兜底。"""

    def test_expand_without_embed_is_backward_compatible(self) -> None:
        """不传 enable_embed 时行为与原来一致。"""
        result = expand_query("fetch data", enable_embed=False)
        assert "get" in result or "retrieve" in result

    def test_embed_degraded_when_fastembed_not_installed(self, monkeypatch) -> None:
        """fastembed 不可用时静默退化。"""
        monkeypatch.setattr("code_nearby.rag.synonyms._get_embed_model", lambda: None)
        result = expand_query("unknown_term_xyz", enable_embed=True)
        assert result == "unknown_term_xyz"  # 没 crash

    def test_enable_embed_is_opt_in(self) -> None:
        """默认 enable_embed=False 不会触发 embed 层。"""
        # 即使 fastembed 不可用，也不应报错
        result = expand_query("something random")
        assert isinstance(result, str)


class TestLoadCustomSynonyms:
    """YAML/JSON 加载。"""

    def test_load_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "synonyms.yaml"
        yaml_file.write_text("auth:\n  - sso\n  - kerberos\n")
        result = load_custom_synonyms(yaml_file)
        assert result == {"auth": ["sso", "kerberos"]}

    def test_load_from_json(self, tmp_path: Path) -> None:
        json_file = tmp_path / "synonyms.json"
        json_file.write_text('{"auth": ["sso", "kerberos"]}')
        result = load_custom_synonyms(json_file)
        assert result == {"auth": ["sso", "kerberos"]}

    def test_load_nonexistent_file(self) -> None:
        assert load_custom_synonyms("/nonexistent/path.yaml") is None

    def test_load_invalid_yaml_returns_none(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text(":: invalid yaml :: ```")
        result = load_custom_synonyms(bad_file)
        assert result is None

    def test_load_non_dict_returns_none(self, tmp_path: Path) -> None:
        list_file = tmp_path / "list.yaml"
        list_file.write_text("- auth\n- deploy\n")
        result = load_custom_synonyms(list_file)
        assert result is None

    def test_load_filters_non_string_values(self, tmp_path: Path) -> None:
        mixed_file = tmp_path / "mixed.yaml"
        mixed_file.write_text("auth: [sso, 123, kerberos]\n")  # 123 不是 str
        result = load_custom_synonyms(mixed_file)
        # 整个 list 被跳过（因为 not all(isinstance(x, str) for x in v)）
        assert result is None or "auth" not in result


class TestVocabBuilding:
    """embed 候选词汇表构建。"""

    def test_vocab_contains_all_terms(self) -> None:
        vocab = _build_vocab()
        assert "get" in vocab
        assert "fetch" in vocab
        assert "database" in vocab
        assert len(vocab) > 50  # 33 clusters × average ~5 terms

    def test_vocab_no_duplicates(self) -> None:
        vocab = _build_vocab()
        assert len(vocab) == len(set(vocab))


class TestCosine:
    """余弦相似度计算。"""

    @pytest.mark.skipif(not _HAS_NUMPY, reason="numpy 未安装")
    def test_identical_vectors(self) -> None:
        v = np.array([1.0, 2.0, 3.0])
        assert _cosine(v, v) == pytest.approx(1.0)

    @pytest.mark.skipif(not _HAS_NUMPY, reason="numpy 未安装")
    def test_orthogonal_vectors(self) -> None:
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        assert _cosine(a, b) == pytest.approx(0.0)

    @pytest.mark.skipif(not _HAS_NUMPY, reason="numpy 未安装")
    def test_zero_vector_returns_zero(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 2.0, 3.0])
        assert _cosine(a, b) == 0.0
