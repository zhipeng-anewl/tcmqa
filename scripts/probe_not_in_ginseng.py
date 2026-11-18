# -*- coding: utf-8 -*-
"""挑「人参里没有」的标志性成分，并逐一到图谱里验证。

思路：选其他中药的**指标性成分**（药典里用来做含量测定的那种），
这样既真实又有辨识度，作为「人参不含」的反例更有意义。
每一步都用图谱核对，不靠印象。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402

# 候选：其他中药的指标性成分
CANDIDATES = [
    "glycyrrhizin", "liquiritin", "isoliquiritigenin",
    "astragaloside iv", "calycosin", "formononetin",
    "tanshinone iia", "tanshinone i", "salvianolic acid b", "cryptotanshinone",
    "berberine", "palmatine", "jatrorrhizine",
    "ephedrine", "pseudoephedrine",
    "ferulic acid", "ligustilide",
    "emodin", "chrysophanol", "rhein",
    "artemisinin", "artemether",
    "matrine", "oxymatrine", "sophoridine",
    "notoginsenoside r1",
    "baicalin", "baicalein", "wogonin",
    "chlorogenic acid", "caffeic acid",
    "rutin", "hyperoside", "hesperidin", "naringin",
    "oleanolic acid", "ursolic acid", "betulinic acid",
    "saikosaponin a", "saikosaponin d",
    "puerarin", "daidzein", "genistein",
    "curcumin", "resveratrol",
    "schisandrin", "gomisin a",
    "aconitine", "mesaconitine",
    "paclitaxel", "camptothecin",
    "ginkgolide a", "bilobalide",
    "imperatorin", "paeoniflorin", "albiflorin",
]


def main() -> None:
    with GraphClient() as c:
        ginseng = {
            str(r["n"]).lower()
            for r in c.read(
                "MATCH (h:Herb {name:'人参'})-[:CONTAINS]->(i:Ingredient) RETURN i.name AS n",
                limit=500,
            )
        }
        print(f"人参成分 {len(ginseng)} 个\n")

        hits = c.read(
            """
            UNWIND $names AS nm
            MATCH (i:Ingredient) WHERE toLower(i.name) = nm
            OPTIONAL MATCH (h:Herb)-[:CONTAINS]->(i)
            RETURN i.name AS name, i.id AS id, i.molecular_weight AS mw,
                   count(DISTINCT h) AS herbs,
                   collect(DISTINCT h.name)[0..3] AS sample
            """,
            {"names": CANDIDATES},
            limit=200,
        )

    found = {r["name"].lower(): r for r in hits}
    print(f"候选命中 {len(found)}/{len(CANDIDATES)}")

    usable = []
    for name, r in found.items():
        if name in ginseng:
            print(f"  [排除] {r['name']} —— 人参里也有")
            continue
        usable.append(r)

    print(f"\n可用于反例 {len(usable)} 个：")
    print(f"  {'英文名':<26}{'分子量':>9}{'含它的药数':>10}  代表中药")
    for r in sorted(usable, key=lambda x: x["herbs"]):
        mw = f"{float(r['mw']):.1f}" if r.get("mw") else "-"
        samples = "、".join(r["sample"][:2])
        print(f"  {r['name']:<26}{mw:>9}{r['herbs']:>10}  {samples}")

    missing = [n for n in CANDIDATES if n not in found]
    if missing:
        print(f"\n图谱里没有的候选（{len(missing)}）: {missing[:8]}")


if __name__ == "__main__":
    main()
