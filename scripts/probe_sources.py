# -*- coding: utf-8 -*-
"""核对几个指标性成分在图谱里的来源中药，看建图数据有没有串味。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402

PAIRS = [
    ("berberine", ["黄连", "黄柏", "三颗针"]),
    ("curcumin", ["姜黄", "郁金"]),
    ("matrine", ["苦参", "山豆根"]),
    ("artemisinin", ["青蒿"]),
    ("resveratrol", ["虎杖"]),
    ("puerarin", ["葛根"]),
]


def main() -> None:
    with GraphClient() as c:
        for ingredient, expected in PAIRS:
            rows = c.read(
                "MATCH (i:Ingredient) WHERE toLower(i.name) = $n "
                "MATCH (h:Herb)-[:CONTAINS]->(i) RETURN h.name AS h",
                {"n": ingredient.lower()},
                limit=300,
            )
            herbs = {r["h"] for r in rows}
            hit = [e for e in expected if e in herbs]
            miss = [e for e in expected if e not in herbs]
            print(f"{ingredient:<16} 关联 {len(herbs):>3} 味 | 命中预期 {hit} | 缺失 {miss}")
            print(f"                 全部: {sorted(herbs)[:10]}")


if __name__ == "__main__":
    main()
