# -*- coding: utf-8 -*-
"""按「成分特征性」重排某味药的成分。

为什么不用靶点数排序：靶点多说明这个成分研究得多、作用广，
但山柰酚、β-谷甾醇、亚油酸这类成分几百味药都有，根本不代表人参。
真正代表人参的是人参皂苷——它们靶点少，但只在极少数药材里出现。

特征性 = 含该成分的中药味数（越少越特征）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402
from tcmqa.settings import DATA_DIR  # noqa: E402


def main() -> None:
    herb = sys.argv[1] if len(sys.argv) > 1 else "人参"
    zh_path = DATA_DIR / "ingredient_zh.json"
    zh = json.loads(zh_path.read_text(encoding="utf-8")) if zh_path.exists() else {}

    with GraphClient() as c:
        rows = c.read(
            """
            MATCH (h:Herb {name:$herb})-[:CONTAINS]->(i:Ingredient)
            OPTIONAL MATCH (other:Herb)-[:CONTAINS]->(i)
            OPTIONAL MATCH (i)-[:TARGETS]->(t:Target)
            RETURN i.name AS name, i.molecular_weight AS mw,
                   count(DISTINCT other) AS herb_count,
                   count(DISTINCT t) AS targets
            ORDER BY herb_count ASC, targets DESC
            """,
            {"herb": herb},
            limit=1000,
        )

    if not rows:
        print("未找到")
        return

    total = len(rows)
    saponins = [r for r in rows if "ginsenoside" in (r["name"] or "").lower()]
    print(f"{herb} 共 {total} 个成分，其中人参皂苷 {len(saponins)} 个\n")

    print("== 最具特征性的 20 个成分（含它的中药味数最少）")
    print(f"  {'英文名':<34}{'中文名':<18}{'同含此成分的药':>8}{'靶点':>5}")
    for r in rows[:20]:
        name = str(r["name"])[:32]
        zname = zh.get(r["name"], "")
        print(f"  {name:<34}{zname:<18}{r['herb_count']:>8}{r['targets']:>5}")

    print("\n== 全部人参皂苷（人参的标志性成分）")
    print(f"  {'英文名':<26}{'中文名':<20}{'同含此成分的药':>8}{'靶点':>5}")
    for r in sorted(saponins, key=lambda x: (-x["targets"], x["herb_count"])):
        name = str(r["name"])[:24]
        zname = zh.get(r["name"], "")[:18]
        print(f"  {name:<26}{zname:<20}{r['herb_count']:>8}{r['targets']:>5}")

    wide = [r for r in rows if r["herb_count"] >= 100]
    print(f"\n对比：同时出现在 100 味以上中药里的成分有 {len(wide)} 个"
          f"（这类不具特征性，例如 {wide[0]['name'] if wide else '-'}）")

    # 写出特征性排序表
    out = Path(__file__).resolve().parent.parent / "docs" / f"{herb}_成分_特征性排序.md"
    lines = [
        f"# {herb} 成分（按特征性排序）",
        "",
        "按「同含该成分的中药味数」升序：越少说明越能代表这味药。",
        "对照：按靶点数排序会把山柰酚、β-谷甾醇这类广布成分排在最前，不具特征性。",
        "",
        "| # | 英文名 | 中文名 | 分子量 | 同含此成分的药 | 靶点数 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(rows, start=1):
        mw = f"{float(r['mw']):.1f}" if r.get("mw") else "—"
        name = str(r["name"]).replace("|", "\\|")
        lines.append(
            f"| {i} | {name} | {zh.get(r['name'], '未翻译')} | {mw} | "
            f"{r['herb_count']} | {r['targets']} |"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n完整表 → {out}")


if __name__ == "__main__":
    main()
