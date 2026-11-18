# -*- coding: utf-8 -*-
"""语义缓存。

两级：
1. 精确缓存：问题归一化后取 sha256 命中，零成本；
2. 语义缓存：把问题向量化，与历史问题比余弦相似度，超过阈值就复用答案。

语义缓存的价值在于把「人参有什么成分」和「人参都含哪些化学成分」当成同一个问题，
客服/问答场景里这种同义改写占比往往超过 30%。代价是可能返回「看起来像但不完全一样」
的答案，所以阈值取 0.95 偏高，宁可多打一次模型也别答错。

工程上要注意：阈值、TTL 都是可配置的，且被问到时能说清「为什么是 0.95」。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from tcmqa.rag.embedder import Embedder
from tcmqa.settings import Settings, get_settings
from tcmqa.store.sqlite import Database

_NORMALIZE_RE = re.compile(r"[\s\u3000]+|[?？。！!，,、；;：:]+")


def normalize_question(question: str) -> str:
    return _NORMALIZE_RE.sub("", question.strip().lower())


def make_key(question: str) -> str:
    return hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()[:32]


@dataclass
class CacheHit:
    answer: str
    payload: dict[str, Any]
    score: float
    kind: str  # exact | semantic


class SemanticCache:
    def __init__(
        self,
        db: Database,
        embedder: Embedder,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.embedder = embedder
        self.settings = settings or get_settings()
        self._vectors: np.ndarray | None = None
        self._keys: list[str] = []
        self._questions: list[str] = []
        self._created: list[float] = []
        self._dirty = True

    # ------------------------------------------------------------------ #
    def _ensure_loaded(self) -> None:
        if not self._dirty and self._vectors is not None:
            return
        rows = self.db.cache_questions()
        vectors, keys, questions, created = [], [], [], []
        for row in rows:
            blob = row.get("embedding")
            if not blob:
                continue
            vec = np.frombuffer(blob, dtype=np.float32)
            if vec.size != 512:
                continue
            vectors.append(vec)
            keys.append(row["key"])
            questions.append(row["question"])
            created.append(row["created_at"])
        self._vectors = np.vstack(vectors) if vectors else None
        self._keys = keys
        self._questions = questions
        self._created = created
        self._dirty = False

    def invalidate(self) -> None:
        self._dirty = True

    # ------------------------------------------------------------------ #
    def get(self, question: str, *, allow_semantic: bool = True) -> CacheHit | None:
        key = make_key(question)
        row = self.db.cache_get(key)
        if row:
            payload = row.get("payload") or {}
            created = float(row.get("created_at") or 0)
            if time.time() - created <= self.settings.cache_ttl_seconds:
                return CacheHit(answer=row["answer"], payload=payload, score=1.0, kind="exact")

        if not allow_semantic:
            return None

        self._ensure_loaded()
        if self._vectors is None or not self._keys:
            return None

        query_vector = self.embedder.encode_query(question)
        scores = self._vectors @ query_vector
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])

        if best_score < self.settings.semantic_cache_threshold:
            return None

        cutoff = time.time() - self.settings.cache_ttl_seconds
        if self._created[best_idx] < cutoff:
            return None

        row = self.db.cache_get(self._keys[best_idx])
        if not row:
            return None
        return CacheHit(
            answer=row["answer"],
            payload=row.get("payload") or {},
            score=best_score,
            kind="semantic",
        )

    # ------------------------------------------------------------------ #
    def put(self, question: str, answer: str, payload: dict[str, Any]) -> None:
        key = make_key(question)
        try:
            vector = self.embedder.encode_query(question).astype(np.float32)
            blob = vector.tobytes()
        except Exception:  # noqa: BLE001 - 向量化失败就只存精确缓存
            blob = None

        self.db.cache_put(
            key,
            question,
            answer,
            payload if len(json.dumps(payload, ensure_ascii=False)) < 20000 else {},
            embedding=blob,
        )
        self._dirty = True

    def stats(self) -> dict[str, Any]:
        return self.db.cache_stats()
