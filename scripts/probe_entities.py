# -*- coding: utf-8 -*-
"""挑选难例要用的实体，确认它们确实存在。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402


def main() -> None:
    with GraphClient() as c:
        for kw in ["雷公藤", "党参", "桂枝", "五味子", "酸枣仁", "远志", "柏子仁"]:
            rows = c.read(
                "MATCH (h:Herb) WHERE h.name CONTAINS $k RETURN h.name AS n LIMIT 3", {"k": kw}
            )
            print("herb", kw, [r["n"] for r in rows])

        for kw in ["curcumin", "resveratrol", "kaempferol", "quercetin"]:
            rows = c.read(
                "MATCH (i:Ingredient) WHERE toLower(i.name) CONTAINS $k RETURN i.name AS n LIMIT 3",
                {"k": kw},
            )
            print("ing", kw, [r["n"] for r in rows])

        for kw in ["psoriasis", "osteoporosis", "migraine", "obesity", "insomnia"]:
            rows = c.read(
                "MATCH (d:Disease) WHERE toLower(d.name) CONTAINS $k RETURN d.name AS n LIMIT 3",
                {"k": kw},
            )
            print("dis", kw, [r["n"] for r in rows])

        # 难例：成分和靶点的英文名，用户可能直接打英文
        rows = c.read(
            "MATCH (h:Herb)-[:CONTAINS]->(i:Ingredient) WHERE toLower(i.name)='curcumin' "
            "RETURN h.name AS n LIMIT 5"
        )
        print("curcumin 关联中药", [r["n"] for r in rows])


if __name__ == "__main__":
    main()
