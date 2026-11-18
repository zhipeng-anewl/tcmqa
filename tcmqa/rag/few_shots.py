# -*- coding: utf-8 -*-
"""少样本示例库。

Text2Cypher 的效果高度依赖示例质量，而示例一旦多起来就会撑爆上下文，
所以这里维护一个「示例池」，运行时按问题相似度动态挑 top-k 拼进 prompt。
这本质上是「对 prompt 做检索」，也是把 RAG 用在提示词上的常见做法。
"""

from __future__ import annotations

from dataclasses import dataclass

from tcmqa.rag.bm25_store import tokenize


@dataclass(frozen=True)
class FewShot:
    question: str
    cypher: str


EXAMPLES: list[FewShot] = [
    FewShot(
        "人参含有哪些化学成分？",
        "MATCH (h:Herb {name:'人参'})-[:CONTAINS]->(i:Ingredient) "
        "RETURN i.name AS ingredient LIMIT 20",
    ),
    FewShot(
        "哪些中药可以治疗糖尿病？",
        "MATCH (h:Herb)-[:TREATS]->(d:Disease) "
        "WHERE toLower(d.name) CONTAINS 'diabetes' "
        "RETURN DISTINCT h.name AS herb LIMIT 20",
    ),
    FewShot(
        "治疗糖尿病的中药一共有多少味？",
        "MATCH (h:Herb)-[:TREATS]->(d:Disease) "
        "WHERE toLower(d.name) CONTAINS 'diabetes' "
        "RETURN count(DISTINCT h) AS herb_count",
    ),
    FewShot(
        "槲皮素作用于哪些靶点蛋白？",
        "MATCH (i:Ingredient)-[:TARGETS]->(t:Target) "
        "WHERE toLower(i.name) = 'quercetin' "
        "RETURN t.name AS target LIMIT 20",
    ),
    FewShot(
        "人参中的成分分别靶向哪些靶点？",
        "MATCH (h:Herb {name:'人参'})-[:CONTAINS]->(i:Ingredient)-[:TARGETS]->(t:Target) "
        "RETURN i.name AS ingredient, t.name AS target LIMIT 30",
    ),
    FewShot(
        "槲皮素的分子量、logP 和口服生物利用度是多少？",
        "MATCH (i:Ingredient) WHERE toLower(i.name) = 'quercetin' "
        "OPTIONAL MATCH (i)-[:HAS_ADME]->(a:IngredientADME) "
        "RETURN i.molecular_weight AS molecular_weight, i.logP AS logP, "
        "a.oral_bioavailability AS oral_bioavailability LIMIT 1",
    ),
    FewShot(
        "华山参和巴戟天为什么能治疗过敏性鼻炎？",
        "MATCH (h:Herb)-[:CONTAINS]->(i:Ingredient)-[:TARGETS]->(t:Target)-[:INVOLVED_IN]->(d:Disease) "
        "WHERE h.name IN ['华山参','巴戟天'] AND toLower(d.name) CONTAINS 'rhinitis' "
        "RETURN h.name AS herb, i.name AS ingredient, t.name AS target, "
        "d.name AS disease LIMIT 30",
    ),
    FewShot(
        "哪些中药含有的成分最多？列出前 10 味",
        "MATCH (h:Herb)-[:CONTAINS]->(i:Ingredient) "
        "RETURN h.name AS herb, count(DISTINCT i) AS ingredient_count "
        "ORDER BY ingredient_count DESC LIMIT 10",
    ),
    FewShot(
        "麻黄治疗哪些疾病？",
        "MATCH (h:Herb {name:'麻黄'})-[:TREATS]->(d:Disease) "
        "RETURN DISTINCT d.name AS disease LIMIT 30",
    ),
    FewShot(
        "柴胡和人参有没有共同成分？",
        "MATCH (h1:Herb {name:'柴胡'})-[:CONTAINS]->(i:Ingredient)<-[:CONTAINS]-(h2:Herb {name:'人参'}) "
        "RETURN i.name AS shared_ingredient LIMIT 30",
    ),
    FewShot(
        "哪些成分既能作用于 EGFR 又能治疗乳腺癌？",
        "MATCH (i:Ingredient)-[:TARGETS]->(t:Target) "
        "WHERE toLower(t.name) CONTAINS 'egfr' "
        "MATCH (i)-[:INDICATED_FOR]->(d:Disease) "
        "WHERE toLower(d.name) CONTAINS 'breast cancer' "
        "RETURN DISTINCT i.name AS ingredient LIMIT 20",
    ),
    FewShot(
        "糖尿病涉及哪些靶点？",
        "MATCH (t:Target)-[:INVOLVED_IN]->(d:Disease) "
        "WHERE toLower(d.name) CONTAINS 'diabetes' "
        "RETURN DISTINCT t.name AS target LIMIT 30",
    ),
]


class FewShotLibrary:
    """按词面重合度检索最相关的示例，避免把 12 条全塞进 prompt。"""

    def __init__(self, examples: list[FewShot] | None = None) -> None:
        self.examples = examples or EXAMPLES
        self._tokens = [set(tokenize(e.question)) for e in self.examples]

    def select(self, question: str, k: int = 3) -> list[FewShot]:
        query_tokens = set(tokenize(question))
        if not query_tokens:
            return self.examples[:k]

        scored = []
        for example, tokens in zip(self.examples, self._tokens):
            overlap = len(query_tokens & tokens)
            union = len(query_tokens | tokens) or 1
            scored.append((overlap / union, example))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:k]]

    @staticmethod
    def render(examples: list[FewShot]) -> str:
        return "\n\n".join(
            f"问题：{e.question}\nCypher: {e.cypher}" for e in examples
        )
