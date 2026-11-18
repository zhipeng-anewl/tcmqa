# -*- coding: utf-8 -*-
"""生成并核对「人参不含」的负样本集。

输出 data/negatives_人参.json，可直接用于评测：
拿这些成分去问系统「人参含不含 X」，正确行为是明确说没有——用来测幻觉。

每一行都做了显式反向核对：确认图谱里人参的 CONTAINS 边不包含该成分。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402
from tcmqa.settings import DATA_DIR  # noqa: E402

SELECTED = [
    "glycyrrhizin", "berberine", "artemisinin", "tanshinone iia",
    "salvianolic acid b", "saikosaponin a", "paeoniflorin", "matrine",
    "oxymatrine", "Aconitine", "Ligustilide", "curcumin",
    "resveratrol", "puerarin", "notoginsenoside r1",
]


def main() -> None:
    zh_path = DATA_DIR / "ingredient_zh.json"
    zh = json.loads(zh_path.read_text(encoding="utf-8")) if zh_path.exists() else {}

    with GraphClient() as c:
        ginseng = {
            str(r["n"]).lower()
            for r in c.read(
                "MATCH (h:Herb {name:'人参'})-[:CONTAINS]->(i:Ingredient) RETURN i.name AS n",
                limit=500,
            )
        }
        rows = c.read(
            """
            UNWIND $names AS nm
            MATCH (i:Ingredient) WHERE toLower(i.name) = nm
            OPTIONAL MATCH (h:Herb)-[:CONTAINS]->(i)
            OPTIONAL MATCH (i)-[:TARGETS]->(t:Target)
            RETURN i.name AS name, i.id AS id, i.molecular_weight AS mw,
                   count(DISTINCT h) AS herbs,
                   collect(DISTINCT h.name)[0..3] AS sources,
                   count(DISTINCT t) AS targets
            """,
            # 查询侧统一小写，否则 "Aconitine" 匹配不上 toLower(name)
            {"names": [n.lower() for n in SELECTED]},
            limit=100,
        )

    by_name = {r["name"].lower(): r for r in rows}
    items = []
    print(f"人参成分 {len(ginseng)} 个；负样本 {len(SELECTED)} 个\n")
    print(f"{'英文名':<24}{'中文名':<14}{'分子量':>8}{'靶点':>5}  来源中药")
    print("-" * 78)

    for name in SELECTED:
        r = by_name.get(name.lower())
        if not r:
            print(f"{name:<24}{'(图谱中不存在)':<14}")
            continue
        in_ginseng = name.lower() in ginseng
        if in_ginseng:
            print(f"{name:<24}!! 人参里也有，不能当负样本")
            continue
        mw = f"{float(r['mw']):.1f}" if r.get("mw") else "-"
        sources = "、".join(r["sources"][:2]) or "—"
        print(f"{r['name']:<24}{zh.get(r['name'], '?'):<14}{mw:>8}{r['targets']:>5}  {sources}")
        items.append(
            {
                "ingredient": r["name"],
                "ingredient_id": r["id"],
                "name_zh": zh.get(r["name"], ""),
                "molecular_weight": r["mw"],
                "targets": r["targets"],
                "herbs_containing": r["herbs"],
                "source_herbs": r["sources"],
                "in_ginseng": False,
                "question": f"人参含有{r['name']}吗？",
            }
        )

    out = DATA_DIR / "negatives_人参.json"
    out.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n共 {len(items)} 个负样本，已写入 {out}")


if __name__ == "__main__":
    main()
