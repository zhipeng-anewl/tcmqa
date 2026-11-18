# -*- coding: utf-8 -*-
"""为金标集挑实体：确认药名存在、疾病名、以及度数较高的成分。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402

CANDIDATE_HERBS = [
    "人参", "麻黄", "黄芪", "枸杞子", "甘草", "当归", "丹参", "黄连", "金银花",
    "板蓝根", "柴胡", "白芍", "陈皮", "半夏", "茯苓", "白术", "川芎", "三七",
]


def main() -> None:
    with GraphClient() as c:
        herbs = c.read(
            "MATCH (h:Herb) WHERE h.name IN $names "
            "OPTIONAL MATCH (h)-[:CONTAINS]->(i:Ingredient) "
            "WITH h, count(DISTINCT i) AS ings "
            "OPTIONAL MATCH (h)-[:TREATS]->(d:Disease) "
            "RETURN h.name AS name, h.effect AS effect, ings, count(DISTINCT d) AS diseases",
            {"names": CANDIDATE_HERBS},
        )
        print("== 候选中药")
        for r in herbs:
            print(f"  {r['name']}\t{r['effect']}\t成分={r['ings']}\t疾病={r['diseases']}")

        missing = set(CANDIDATE_HERBS) - {r["name"] for r in herbs}
        if missing:
            print("  !! 不存在:", missing)

        print("\n== 高频成分（按靶点数）")
        for r in c.read(
            "MATCH (i:Ingredient)-[:TARGETS]->(t:Target) "
            "RETURN i.name AS name, count(DISTINCT t) AS targets "
            "ORDER BY targets DESC LIMIT 12"
        ):
            print(f"  {r['name']}\t{r['targets']}")

        print("\n== 疾病（按关联中药数）")
        for r in c.read(
            "MATCH (h:Herb)-[:TREATS]->(d:Disease) "
            "RETURN d.name AS name, count(DISTINCT h) AS herbs "
            "ORDER BY herbs DESC LIMIT 12"
        ):
            print(f"  {r['name']}\t{r['herbs']}")

        print("\n== 关键词疾病")
        for kw in ["diabetes", "asthma", "hypertension", "insomnia", "obesity", "depression"]:
            rows = c.read(
                "MATCH (d:Disease) WHERE toLower(d.name) CONTAINS $kw "
                "RETURN d.name AS name LIMIT 4", {"kw": kw}
            )
            print(f"  {kw}: {[r['name'] for r in rows]}")

        print("\n== 被高频中药关联的成分")
        for r in c.read(
            "MATCH (h:Herb)-[:CONTAINS]->(i:Ingredient) "
            "RETURN i.name AS name, count(DISTINCT h) AS herbs "
            "ORDER BY herbs DESC LIMIT 10"
        ):
            print(f"  {r['name']}\t{r['herbs']}")


if __name__ == "__main__":
    main()
