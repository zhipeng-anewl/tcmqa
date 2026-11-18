# -*- coding: utf-8 -*-
"""评测指标与 RRF 融合的单元测试（纯函数，无需外部依赖）。"""

from __future__ import annotations

import pytest

from tcmqa.eval.metrics import (
    extract_values,
    number_matches,
    numbers_in,
    percentile,
    set_scores,
)
from tcmqa.rag.bm25_store import ScoredDoc, rrf_fuse, tokenize
from tcmqa.rag.corpus import Document


# ---------------------------------------------------------------------- #
class TestSetScores:
    def test_perfect_match(self):
        scores = set_scores({"a", "b"}, {"a", "b"})
        assert scores["f1"] == 1.0

    def test_disjoint(self):
        scores = set_scores({"a"}, {"b"})
        assert scores["f1"] == 0.0

    def test_partial(self):
        scores = set_scores({"a", "b", "c"}, {"a", "b", "d"})
        assert scores["precision"] == pytest.approx(2 / 3, abs=1e-3)
        assert scores["recall"] == pytest.approx(2 / 3, abs=1e-3)

    def test_empty_pred(self):
        assert set_scores(set(), {"a"})["f1"] == 0.0

    def test_both_empty(self):
        assert set_scores(set(), set())["f1"] == 1.0

    def test_large_gold_uses_precision_only(self):
        """标准集大于 30 时，召回不可比，F1 退化为精度。"""
        pred = {f"x{i}" for i in range(10)}
        gold = {f"x{i}" for i in range(100)}
        scores = set_scores(pred, gold)
        assert scores["f1"] == 1.0
        assert scores["recall"] == pytest.approx(0.1, abs=1e-3)


class TestExtractValues:
    def test_filters_by_universe(self):
        rows = [{"ingredient": "quercetin", "score": 0.9}, {"ingredient": "not_a_ingredient"}]
        universe = {"quercetin"}
        assert extract_values(rows, "Ingredient", universe) == {"quercetin"}

    def test_handles_lists(self):
        rows = [{"items": ["quercetin", "kaempferol"]}]
        universe = {"quercetin", "kaempferol"}
        assert extract_values(rows, "Ingredient", universe) == {"quercetin", "kaempferol"}


class TestNumbers:
    def test_numbers_in_nested(self):
        assert 500.0 in numbers_in({"count": 500})
        assert 3.5 in numbers_in([{"v": 3.5}])
        assert 12.0 in numbers_in("共 12 味中药")

    def test_ignores_bool(self):
        assert numbers_in(True) == []

    def test_number_matches_tolerance(self):
        assert number_matches([100.0], 100.0, 0.05)
        assert number_matches([104.0], 100.0, 0.05)
        assert not number_matches([120.0], 100.0, 0.05)

    def test_number_matches_zero(self):
        assert number_matches([0.0], 0.0, 0.05)
        assert not number_matches([5.0], 0.0, 0.05)


class TestPercentile:
    def test_single(self):
        assert percentile([10.0], 0.95) == 10.0

    def test_median(self):
        assert percentile([1.0, 2.0, 3.0], 0.5) == 2.0

    def test_p95(self):
        values = list(range(1, 101))
        assert percentile(values, 0.95) == pytest.approx(95.05, abs=0.2)

    def test_empty(self):
        assert percentile([], 0.5) == 0.0


# ---------------------------------------------------------------------- #
class TestTokenize:
    def test_removes_stopwords(self):
        tokens = tokenize("人参含有哪些化学成分？")
        assert "哪些" not in tokens
        assert any("人参" in t for t in tokens)

    def test_fallback_on_empty(self):
        assert tokenize("的了吗")  # 不能返回空列表


class TestRRF:
    def _doc(self, doc_id: str) -> Document:
        return Document(id=doc_id, kind="herb", title=doc_id, text=doc_id)

    def test_fusion_promotes_agreement(self):
        a = ScoredDoc(doc=self._doc("both"), score=0.9, source="vector")
        b = ScoredDoc(doc=self._doc("only_vec"), score=0.95, source="vector")
        c = ScoredDoc(doc=self._doc("both"), score=3.0, source="bm25")
        d = ScoredDoc(doc=self._doc("only_bm25"), score=2.0, source="bm25")

        fused = rrf_fuse({"vector": [a, b], "bm25": [c, d]}, k=60, top_n=3)
        assert fused[0].doc.id == "both"
        assert set(fused[0].sources) == {"vector", "bm25"}

    def test_top_n_limit(self):
        hits = [ScoredDoc(doc=self._doc(str(i)), score=1.0, source="vector") for i in range(10)]
        fused = rrf_fuse({"vector": hits}, top_n=3)
        assert len(fused) == 3
