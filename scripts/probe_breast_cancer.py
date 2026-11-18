# -*- coding: utf-8 -*-
"""乳腺癌这个案例的数据实况：TREATS 边有没有区分度，机制链路能筛出什么。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402


def main() -> None:
    with GraphClient() as c:
        total_herb = c.scalar("MATCH (h:Herb) RETURN count(h) AS c")
        treats = c.scalar(
            "MATCH (h:Herb)-[:TREATS]->(d:Disease {name:'breast cancer'}) "
            "RETURN count(DISTINCT h) AS c"
        )
        print(f"中药总数 {total_herb}，其中 TREATS→breast cancer 的 {treats} 味 "
              f"({treats / total_herb:.1%})")

        # 每个疾病被多少味药 TREATS，看看是不是普遍现象
        dense = c.read(
            "MATCH (h:Herb)-[:TREATS]->(d:Disease) "
            "WITH d, count(DISTINCT h) AS herbs "
            "RETURN d.name AS disease, herbs ORDER BY herbs DESC LIMIT 5"
        )
        print("\nTREATS 边最密集的疾病（说明这条边几乎没有区分度）:")
        for r in dense:
            print(f"  {r['disease']}: {r['herbs']} 味")

        # 机制链路：药 → 成分 → 靶点 → 参与乳腺癌
        mech = c.read(
            """
            MATCH (h:Herb)-[:CONTAINS]->(i:Ingredient)-[:TARGETS]->(t:Target)
                  -[:INVOLVED_IN]->(d:Disease)
            WHERE toLower(d.name) CONTAINS 'breast cancer'
            RETURN h.name AS herb,
                   count(DISTINCT i) AS ingredients,
                   count(DISTINCT t) AS targets
            ORDER BY targets DESC, ingredients DESC
            LIMIT 15
            """
        )
        mech_total = c.scalar(
            """
            MATCH (h:Herb)-[:CONTAINS]->(i:Ingredient)-[:TARGETS]->(t:Target)
                  -[:INVOLVED_IN]->(d:Disease)
            WHERE toLower(d.name) CONTAINS 'breast cancer'
            RETURN count(DISTINCT h) AS c
            """
        )
        print(f"\n有「药→成分→靶点→乳腺癌」机制链路的药: {mech_total} 味")
        print("按关联靶点数排名（证据更强的候选）:")
        print(f"  {'中药':<10}{'成分数':>8}{'靶点数':>8}")
        for r in mech:
            print(f"  {r['herb']:<10}{r['ingredients']:>8}{r['targets']:>8}")

        # 乳腺癌相关靶点有多少
        targets = c.scalar(
            "MATCH (t:Target)-[:INVOLVED_IN]->(d:Disease) "
            "WHERE toLower(d.name) CONTAINS 'breast cancer' RETURN count(DISTINCT t) AS c"
        )
        print(f"\n图谱里『参与乳腺癌』的靶点: {targets} 个")


if __name__ == "__main__":
    main()
