# -*- coding: utf-8 -*-
"""看人参的成分构成：数量、名称形态、有多少是有效化学名。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402

# 缩写/短代号：大写 2-5 个字母，或明显不是 IUPAC 名
ABBR_RE = re.compile(r"^[A-Z0-9]{2,6}$")


def main() -> None:
    with GraphClient() as c:
        rows = c.read(
            """
            MATCH (h:Herb {name:'人参'})-[:CONTAINS]->(i:Ingredient)
            OPTIONAL MATCH (i)-[:TARGETS]->(t:Target)
            OPTIONAL MATCH (i)-[:HAS_ADME]->(a:IngredientADME)
            RETURN i.name AS name, i.id AS id, i.molecular_weight AS mw,
                   count(DISTINCT t) AS targets, a.oral_bioavailability AS ob
            ORDER BY targets DESC, i.molecular_weight DESC
            """,
            limit=500,
        )

    print(f"人参成分数: {len(rows)}")

    abbr = [r for r in rows if ABBR_RE.match(r["name"] or "")]
    long_names = [r for r in rows if len(r["name"] or "") > 25]
    print(f"  疑似缩写/代号: {len(abbr)}")
    print(f"  超长 IUPAC 名: {len(long_names)}")
    print(f"  其他: {len(rows) - len(abbr) - len(long_names)}")

    print("\n== 按靶点数排名前 25")
    print(f"  {'英文名':<42}{'靶点':>5}{'分子量':>9}")
    for r in rows[:25]:
        mw = f"{float(r['mw']):.1f}" if r.get("mw") else "-"
        name = (r["name"] or "")[:40]
        print(f"  {name:<42}{r['targets']:>5}{mw:>9}")

    print("\n== 缩写类样例（这类没法翻译）")
    for r in abbr[:13]:
        print(f"  {r['name']}")

    print("\n== 靶点为 0 的成分数:", sum(1 for r in rows if r["targets"] == 0))


if __name__ == "__main__":
    main()
