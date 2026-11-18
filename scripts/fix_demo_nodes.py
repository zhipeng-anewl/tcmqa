# -*- coding: utf-8 -*-
"""整理演示版用到的实体 fixture：统一命名 + 生成搜索索引。

GraphTab 的流程是：
    /api/graph/search?q=糖尿病  -> 拿到 {name: "Diabetes mellitus"}
    /api/graph/node?name=Diabetes mellitus -> 拿节点详情
所以 fixture 文件名必须用**节点真实名字**，中文只是搜索时的别名。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "demo" / "node"

# 文件名 -> (展示用的中文别名, 说明)
ALIAS = {
    "Diabetes mellitus": "糖尿病",
    "Quercetin": "槲皮素",
}

ORDER = ["人参", "麻黄", "枸杞子", "Diabetes mellitus", "Quercetin", "Ginsenoside Rb1"]


def main() -> None:
    # 旧脚本用查询词当文件名，这里统一改成节点真实名
    for src in OUT.glob("*.json"):
        data = json.loads(src.read_text(encoding="utf-8"))
        real = data.get("name")
        if real and src.stem != real:
            (OUT / f"{real}.json").write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
            )
            src.unlink()
            print(f"重命名 {src.stem} -> {real}")

    items = []
    for name in ORDER:
        path = OUT / f"{name}.json"
        if not path.exists():
            print(f"跳过（缺失）：{name}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        items.append(
            {
                "name": name,
                "label": data.get("label", ""),
                "id": (data.get("properties") or {}).get("id", ""),
                "alias": ALIAS.get(name, ""),
                "neighbors": data.get("neighbor_count", 0),
            }
        )

    search = OUT.parent / "search.json"
    search.write_text(
        json.dumps({"items": items}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"\n搜索索引：{len(items)} 个实体")
    for it in items:
        print(f"  {it['name']:20s} {it['label']:12s} {it['neighbors']:>5} 邻居  {it['alias']}")


if __name__ == "__main__":
    main()
