# -*- coding: utf-8 -*-
"""实体链接。

图谱里中药是中文、成分/靶点是英文，用户却用中文提问（"槲皮素"）。
不做链接，Text2Cypher 就只能靠模型瞎猜英文名，命中率很低。

链接分四级，从严格到宽松：
  1. 精确匹配（忽略大小写）—— 最高置信
  2. 别名匹配（LLM 给出的英文名/同义词）
  3. 双向子串匹配 —— 处理"人参" vs "人参皂苷"这类包含关系
  4. 编辑距离模糊匹配 —— 兜底错别字

另外单独做一层「功效分类」识别：用户说"清热解毒的药"，"清热解毒药"是
图谱里的 effect 属性值，不是节点，所以不能靠实体匹配，要单独扫一遍类目表。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from tcmqa.kg.client import GraphClient

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = ("Herb", "Ingredient", "Target", "Disease")


@dataclass
class Candidate:
    name: str
    node_id: str
    score: float
    method: str  # exact / alias / contains / fuzzy


@dataclass
class LinkResult:
    raw: str
    etype: str
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return bool(self.candidates)

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    def names(self, k: int = 5) -> list[str]:
        seen: list[str] = []
        for c in self.candidates:
            if c.name not in seen:
                seen.append(c.name)
        return seen[:k]

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "type": self.etype,
            "matched": self.matched,
            "candidates": [
                {"name": c.name, "id": c.node_id, "score": round(c.score, 3), "method": c.method}
                for c in self.candidates[:5]
            ],
        }


class EntityLinker:
    """内存别名索引，启动时从图谱一次性加载。"""

    def __init__(self, client: GraphClient) -> None:
        self.client = client
        self._index: dict[str, dict[str, list[tuple[str, str]]]] = {}
        self._effects: list[str] = []
        self._loaded = False

    # ------------------------------------------------------------------ #
    def load(self, force: bool = False) -> None:
        if self._loaded and not force:
            return

        index: dict[str, dict[str, list[tuple[str, str]]]] = {}
        for label in SUPPORTED_TYPES:
            rows = self.client.read(
                f"MATCH (n:`{label}`) RETURN n.name AS name, n.id AS id", limit=50_000
            )
            bucket: dict[str, list[tuple[str, str]]] = {}
            for r in rows:
                name = str(r.get("name") or "").strip()
                if not name:
                    continue
                bucket.setdefault(name.lower(), []).append((name, str(r.get("id") or "")))
            index[label] = bucket
            logger.info("实体链接索引已加载 %s=%d", label, len(bucket))

        self._index = index
        self._effects = [
            str(r["e"])
            for r in self.client.read(
                "MATCH (h:Herb) RETURN DISTINCT h.effect AS e", limit=5000
            )
            if r.get("e")
        ]
        logger.info("功效分类已加载 %d 类", len(self._effects))
        self._loaded = True

    # ------------------------------------------------------------------ #
    def link(self, raw: str, etype: str, aliases: list[str] | None = None) -> LinkResult:
        self.load()
        bucket = self._index.get(etype, {})
        result = LinkResult(raw=raw, etype=etype)
        if not bucket:
            return result

        names = list(bucket.keys())
        texts: list[tuple[str, str]] = [(raw or "", "exact")] + [
            (a, "alias") for a in (aliases or []) if a
        ]

        found: dict[str, Candidate] = {}

        def add(name: str, node_id: str, score: float, method: str) -> None:
            prev = found.get(name)
            if prev is None or score > prev.score:
                found[name] = Candidate(name, node_id, score, method)

        # 1 & 2：精确 / 别名
        for text, method in texts:
            key = text.strip().lower()
            if not key:
                continue
            for name, node_id in bucket.get(key, []):
                add(name, node_id, 1.0 if method == "exact" else 0.95, method)

        # 3：双向子串
        if not found:
            for text, _ in texts:
                key = text.strip().lower()
                if len(key) < 2:
                    continue
                for name_lower, entries in bucket.items():
                    if key in name_lower or (len(name_lower) >= 2 and name_lower in key):
                        score = 0.75 if key in name_lower else 0.7
                        for name, node_id in entries:
                            add(name, node_id, score, "contains")
                if len(found) >= 10:
                    break

        # 4：编辑距离兜底，只在什么都没匹到时做
        if not found:
            for text, _ in texts:
                key = text.strip().lower()
                if len(key) < 2:
                    continue
                best_ratio, best_key = 0.0, ""
                for name_lower in names if len(names) <= 8000 else names[:8000]:
                    ratio = SequenceMatcher(None, key, name_lower).ratio()
                    if ratio > best_ratio:
                        best_ratio, best_key = ratio, name_lower
                if best_ratio >= 0.82 and best_key:
                    for name, node_id in bucket[best_key]:
                        add(name, node_id, best_ratio, "fuzzy")

        result.candidates = sorted(found.values(), key=lambda c: c.score, reverse=True)[:10]
        return result

    def detect_effects(self, question: str) -> list[str]:
        """识别问题中提到的功效分类（类目是属性值，不是节点）。"""
        self.load()
        hits: list[str] = []
        compact = re.sub(r"\s+", "", question)
        for effect in self._effects:
            stem = effect[:-1] if effect.endswith("药") else effect
            if stem and stem in compact:
                hits.append(effect)
        return sorted(hits, key=len, reverse=True)

    @property
    def effect_categories(self) -> list[str]:
        self.load()
        return list(self._effects)

    def name_universe(self, etype: str) -> set[str]:
        """某个标签下所有实体的名字集合。

        评测时用它把「系统返回的值」过滤成「确实属于该类型的实体」，
        这样就算 Cypher 的列名和标准答案不一致，也能公平比对集合。
        """
        self.load()
        bucket = self._index.get(etype, {})
        names: set[str] = set()
        for entries in bucket.values():
            for name, _ in entries:
                names.add(name)
        return names
