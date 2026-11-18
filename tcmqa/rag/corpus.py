# -*- coding: utf-8 -*-
"""把图谱「翻译」成自然语言语料，供向量检索使用。

为什么需要这一步：图谱是结构化的三元组，用户问的却是「有哪些清热解毒的药」
「手脚冰凉适合吃什么」这种**语义**问题，Text2Cypher 很难稳定翻译，
但把每个中药写成一段自然语言简介，向量检索就能直接命中。

所以这里做的是典型的 GraphRAG 思路——**图谱负责精确关系，语料负责语义召回**，
两条路互相补位。语料不是凭空生成的，全部由图谱聚合出来，保证与图谱一致。

疾病名在图谱里是英文，中文提问召回不到，因此额外支持 data/disease_zh.json
（由 scripts/translate_diseases.py 用 LLM 批量生成的中英对照表）做双语拼接。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tcmqa.kg.client import GraphClient
from tcmqa.settings import DATA_DIR

logger = logging.getLogger(__name__)

DISEASE_ZH_PATH = DATA_DIR / "disease_zh.json"


@dataclass
class Document:
    id: str
    kind: str  # herb / effect / disease / ingredient
    title: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "text": self.text,
            "meta": self.meta,
        }


def _load_disease_zh() -> dict[str, str]:
    if not DISEASE_ZH_PATH.exists():
        return {}
    try:
        return json.loads(DISEASE_ZH_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("disease_zh.json 解析失败，忽略")
        return {}


# ---------------------------------------------------------------------- #
def _herb_docs(client: GraphClient) -> list[Document]:
    rows = client.read(
        """
        MATCH (h:Herb)
        OPTIONAL MATCH (h)-[:CONTAINS]->(i:Ingredient)
        WITH h, collect(DISTINCT i.name)[0..10] AS ingredients
        OPTIONAL MATCH (h)-[:TREATS]->(d:Disease)
        WITH h, ingredients, collect(DISTINCT d.name)[0..6] AS diseases
        RETURN h.id AS id, h.name AS name, h.effect AS effect,
               ingredients, diseases,
               size(ingredients) AS ingredient_cnt
        ORDER BY h.id
        """,
        limit=5000,
    )
    zh = _load_disease_zh()
    docs: list[Document] = []
    for r in rows:
        name = r.get("name") or ""
        effect = r.get("effect") or "未分类"
        ings = [x for x in (r.get("ingredients") or []) if x]
        diseases = [zh.get(d, d) for d in (r.get("diseases") or []) if d]

        parts = [f"中药：{name}。", f"功效分类：{effect}。"]
        if ings:
            parts.append(f"含有化学成分，例如：{'、'.join(ings)}。")
        if diseases:
            parts.append(f"可用于治疗：{'、'.join(diseases)}。")
        parts.append(f"（编号 {r.get('id')}）")

        docs.append(
            Document(
                id=str(r.get("id")),
                kind="herb",
                title=name,
                text="".join(parts),
                meta={
                    "name": name,
                    "effect": effect,
                    "ingredients": ings,
                    "diseases": diseases,
                },
            )
        )
    return docs


def _effect_docs(client: GraphClient) -> list[Document]:
    rows = client.read(
        """
        MATCH (h:Herb)
        WHERE h.effect IS NOT NULL AND h.effect <> ''
        WITH h.effect AS effect, collect(h.name) AS herbs
        RETURN effect, size(herbs) AS cnt, herbs[0..15] AS sample
        ORDER BY cnt DESC
        """,
        limit=1000,
    )
    docs = []
    for r in rows:
        effect = r.get("effect") or ""
        sample = [x for x in (r.get("sample") or []) if x]
        docs.append(
            Document(
                id=f"EFF_{effect}",
                kind="effect",
                title=effect,
                text=(
                    f"功效分类：{effect}。该类别共收录 {r.get('cnt')} 味中药，"
                    f"代表药材有：{'、'.join(sample)}。"
                    f"想找{effect}时可以看这些中药。"
                ),
                meta={"effect": effect, "count": r.get("cnt"), "sample": sample},
            )
        )
    return docs


def _disease_docs(client: GraphClient) -> list[Document]:
    rows = client.read(
        """
        MATCH (d:Disease)
        OPTIONAL MATCH (h:Herb)-[:TREATS]->(d)
        WITH d, collect(DISTINCT h.name)[0..6] AS herbs
        OPTIONAL MATCH (t:Target)-[:INVOLVED_IN]->(d)
        RETURN d.id AS id, d.name AS name, d.icd10 AS icd10,
               herbs, collect(DISTINCT t.name)[0..5] AS targets
        ORDER BY d.id
        """,
        limit=5000,
    )
    zh = _load_disease_zh()
    docs = []
    for r in rows:
        name = r.get("name") or ""
        cn = zh.get(name, "")
        herbs = [x for x in (r.get("herbs") or []) if x]
        targets = [x for x in (r.get("targets") or []) if x]

        head = f"疾病：{name}" + (f"（{cn}）" if cn else "") + "。"
        parts = [head]
        if r.get("icd10"):
            parts.append(f"ICD-10 编码 {r['icd10']}。")
        if herbs:
            parts.append(f"图谱中记载可治疗该病的中药有：{'、'.join(herbs)}。")
        if targets:
            parts.append(f"与该病相关的靶点包括：{'、'.join(targets)}。")

        docs.append(
            Document(
                id=str(r.get("id")),
                kind="disease",
                title=cn or name,
                text="".join(parts),
                meta={"name": name, "name_zh": cn, "herbs": herbs, "targets": targets},
            )
        )
    return docs


def _ingredient_docs(client: GraphClient) -> list[Document]:
    rows = client.read(
        """
        MATCH (i:Ingredient)
        OPTIONAL MATCH (i)-[:TARGETS]->(t:Target)
        WITH i, collect(DISTINCT t.name)[0..5] AS targets, count(DISTINCT t) AS target_cnt
        OPTIONAL MATCH (i)-[:INDICATED_FOR]->(d:Disease)
        RETURN i.id AS id, i.name AS name, i.molecular_weight AS mw, i.logP AS logp,
               targets, target_cnt, collect(DISTINCT d.name)[0..4] AS diseases
        ORDER BY target_cnt DESC
        """,
        limit=20000,
    )
    docs = []
    for r in rows:
        name = r.get("name") or ""
        targets = [x for x in (r.get("targets") or []) if x]
        diseases = [x for x in (r.get("diseases") or []) if x]
        parts = [f"化学成分：{name}。"]
        if r.get("mw"):
            parts.append(f"分子量 {round(float(r['mw']), 2)}。")
        if r.get("logp") is not None:
            parts.append(f"logP {r['logp']}。")
        if targets:
            parts.append(f"作用于 {r.get('target_cnt')} 个靶点，例如：{'、'.join(targets)}。")
        if diseases:
            parts.append(f"与疾病相关：{'、'.join(diseases)}。")
        docs.append(
            Document(
                id=str(r.get("id")),
                kind="ingredient",
                title=name,
                text="".join(parts),
                meta={"name": name, "targets": targets, "diseases": diseases},
            )
        )
    return docs


# ---------------------------------------------------------------------- #
def build_corpus(client: GraphClient, include_ingredients: bool = False) -> list[Document]:
    docs: list[Document] = []
    for name, builder in (
        ("herb", _herb_docs),
        ("effect", _effect_docs),
        ("disease", _disease_docs),
    ):
        part = builder(client)
        logger.info("语料 %s: %d 篇", name, len(part))
        docs.extend(part)

    if include_ingredients:
        part = _ingredient_docs(client)
        logger.info("语料 ingredient: %d 篇", len(part))
        docs.extend(part)

    return docs


def corpus_path(kind: str = "all") -> Path:
    return DATA_DIR / "index" / f"corpus_{kind}.jsonl"
