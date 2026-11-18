# -*- coding: utf-8 -*-
"""BM25 关键词检索。

为什么不只靠向量检索：向量对**专有名词和精确词**不敏感——"槲皮素"和"木犀草素"
在语义空间里非常接近，但用户要的就是那个具体成分。BM25 靠词频精确命中，
两者用 RRF 融合后，精确词和语义两个方向都能覆盖，这就是常说的混合检索。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

import jieba

from tcmqa.rag.corpus import Document
from tcmqa.rag.vector_store import ScoredDoc

# 中文里高频但无检索价值的词
STOPWORDS = {
    "的", "了", "是", "在", "有", "和", "与", "及", "或", "对", "把", "被", "就", "都",
    "也", "还", "而", "但", "如果", "因为", "所以", "这个", "那个", "这些", "那些",
    "什么", "哪些", "怎么", "如何", "为什么", "吗", "呢", "吧", "啊", "我", "你", "他",
    "它", "我们", "你们", "他们", "可以", "能够", "一个", "一些", "请", "告诉", "介绍",
    "哪些中药", "中药", "药材", "有没有", "是否", "多少", "几个", "作用", "功效",
}

_PUNCT_RE = re.compile(r"[\s\u3000-\u303f\uff00-\uffef!-/:-@\[-`{-~]+")


def tokenize(text: str) -> list[str]:
    """切词 + 去停用词 + 去标点。英文统一小写，保留连字符（如 caco-2）。"""
    cleaned = _PUNCT_RE.sub(" ", text).lower()
    tokens = []
    for token in jieba.lcut(cleaned):
        token = token.strip()
        if not token or token in STOPWORDS:
            continue
        if len(token) == 1 and token.isascii():
            continue  # 单个英文字母无意义
        tokens.append(token)
    return tokens or [cleaned.strip() or text[:20]]


class BM25Store:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.docs: list[Document] = []
        self._tokens: list[list[str]] = []
        self._bm25 = None
        self.k1 = k1
        self.b = b

    def __len__(self) -> int:
        return len(self.docs)

    # ------------------------------------------------------------------ #
    def build(self, docs: Sequence[Document]) -> None:
        from rank_bm25 import BM25Okapi

        self.docs = list(docs)
        self._tokens = [tokenize(d.text) for d in self.docs]
        self._bm25 = BM25Okapi(self._tokens, k1=self.k1, b=self.b)

    def search(self, query: str, k: int = 8) -> list[ScoredDoc]:
        if self._bm25 is None or not self.docs:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        return [
            ScoredDoc(doc=self.docs[i], score=float(scores[i]), source="bm25")
            for i in order
            if scores[i] > 0
        ]


@dataclass
class FusedDoc:
    doc: Document
    score: float
    sources: list[str]


def rrf_fuse(
    result_lists: dict[str, list[ScoredDoc]],
    k: int = 60,
    top_n: int = 6,
) -> list[FusedDoc]:
    """Reciprocal Rank Fusion：只用排名不用分数，天然规避两路分数量纲不同的问题。

    score(d) = Σ 1 / (k + rank_i(d))
    """
    scores: dict[str, float] = {}
    docs: dict[str, Document] = {}
    sources: dict[str, list[str]] = {}

    for source_name, results in result_lists.items():
        for rank, item in enumerate(results, start=1):
            key = item.doc.id
            docs[key] = item.doc
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            sources.setdefault(key, []).append(source_name)

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [
        FusedDoc(doc=docs[key], score=round(score, 6), sources=sources[key])
        for key, score in ordered
    ]
