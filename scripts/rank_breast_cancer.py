# -*- coding: utf-8 -*-
"""按「靶点特异性」重排乳腺癌相关中药。

为什么需要重排：图谱里 502 味药中有 500 味都有一条通往乳腺癌的边，
直接列出来等于没筛。而按靶点数排序又会偏向成分多的药（度数偏差）。

特异性 = 该药作用于的靶点里，参与乳腺癌的比例。
基线 = 乳腺癌相关靶点 34 / 总靶点 3340 ≈ 1%，也就是随机一味药的靶点里
只有 1% 落在乳腺癌上；远高于 1% 的药才值得优先看。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402


def main() -> None:
    with GraphClient() as c:
        total_targets = c.scalar("MATCH (t:Target) RETURN count(t) AS c")
        bc_targets = c.scalar(
            "MATCH (t:Target)-[:INVOLVED_IN]->(d:Disease) "
            "WHERE toLower(d.name) CONTAINS 'breast cancer' "
            "RETURN count(DISTINCT t) AS c"
        )
        base = bc_targets / total_targets
        print(f"总靶点 {total_targets}，其中参与乳腺癌 {bc_targets}，基线 {base:.1%}")
        print("（任意一味药的靶点里，期望只有约 "
              f"{base:.1%} 落在乳腺癌上；明显高于它的才算有富集）\n")

        rows = c.read(
            """
            MATCH (h:Herb)-[:CONTAINS]->(i:Ingredient)-[:TARGETS]->(t:Target)
            WITH h, collect(DISTINCT t) AS targets
            WITH h, size(targets) AS total, targets
            UNWIND targets AS t
            MATCH (t)-[:INVOLVED_IN]->(d:Disease)
            WHERE toLower(d.name) CONTAINS 'breast cancer'
            WITH h, total, count(DISTINCT t) AS bc
            WHERE bc >= 3
            RETURN h.name AS herb, bc, total,
                   toFloat(bc) / total AS specificity,
                   toFloat(bc) / total / $base AS lift
            ORDER BY lift DESC, bc DESC
            LIMIT 20
            """,
            {"base": base},
            limit=20,
        )

        print(f"{'中药':<10}{'乳腺癌靶点':>10}{'总靶点':>8}{'特异性':>9}{'富集倍数':>10}")
        for r in rows:
            print(f"{r['herb']:<10}{r['bc']:>10}{r['total']:>8}"
                  f"{r['specificity']:>9.1%}{r['lift']:>9.1f}x")

        # 对照：按靶点数排的前几名，特异性如何
        print("\n对照——若只按靶点数排序（度数偏差），前几名其实特异性都不高:")
        naive = c.read(
            """
            MATCH (h:Herb)-[:CONTAINS]->(i:Ingredient)-[:TARGETS]->(t:Target)
                  -[:INVOLVED_IN]->(d:Disease)
            WHERE toLower(d.name) CONTAINS 'breast cancer'
            WITH h, count(DISTINCT t) AS bc
            ORDER BY bc DESC LIMIT 5
            MATCH (h)-[:CONTAINS]->(ii:Ingredient)-[:TARGETS]->(tt:Target)
            RETURN h.name AS herb, count(DISTINCT tt) AS total
            """,
            limit=10,
        )
        for r in naive:
            print(f"  {r['herb']:<10} 总靶点 {r['total']}")


if __name__ == "__main__":
    main()
