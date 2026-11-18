# -*- coding: utf-8 -*-
"""规划器规则降级与缓存 key 的单元测试。

不调 LLM：只测「LLM 挂了也能给出合理意图」这条兜底路径，
以及缓存 key 的归一化是否符合预期。
"""

from __future__ import annotations

import pytest

from tcmqa.rag.cache import make_key, normalize_question
from tcmqa.rag.planner import _heuristic_intent


class TestHeuristicIntent:
    @pytest.mark.parametrize(
        "question,expected",
        [
            ("你好", "chitchat"),
            ("你能做什么？", "chitchat"),
            ("为什么麻黄能治疗哮喘？", "mechanism"),
            ("人参治疗哮喘的作用机制", "mechanism"),
            ("治疗乳腺癌的中药有多少味？", "aggregate"),
            ("成分数量最多的 5 味药", "aggregate"),
            ("人参含有哪些化学成分？", "relation"),
            ("麻黄可以治疗哪些疾病？", "relation"),
            ("手脚冰凉适合吃什么", "semantic"),
        ],
    )
    def test_intents(self, question, expected):
        assert _heuristic_intent(question) == expected

    def test_medical_question_is_out_of_scope(self):
        assert _heuristic_intent("我每天吃人参多少克合适？") == "out_of_scope"


class TestCacheKey:
    def test_normalization_ignores_punctuation_and_space(self):
        assert normalize_question("人参 含有哪些成分？") == normalize_question("人参含有哪些成分")

    def test_same_question_same_key(self):
        assert make_key("人参含有哪些成分？") == make_key(" 人参含有哪些成分 ")

    def test_different_question_different_key(self):
        assert make_key("人参含有哪些成分？") != make_key("麻黄含有哪些成分？")
