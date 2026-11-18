# -*- coding: utf-8 -*-
"""验证中文病名检索：图搜索、节点详情、语义检索三条路径。"""

from __future__ import annotations

import sys

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=120.0) as c:
        print("== 图谱搜索（中文 / 英文）")
        for q in ["糖尿病", "哮喘", "失眠", "乳腺癌", "Diabetes mellitus", "人参", "Asthma"]:
            r = c.get("/api/graph/search", params={"q": q, "limit": 5}).json()
            items = r.get("results") or []
            desc = ", ".join(
                f"{x['name']}" + (f"（{x['alias']}）" if x.get("alias") else "")
                for x in items[:3]
            )
            print(f"  {q:<18} {len(items)} 条  {desc}")

        print("\n== 节点详情（用中文名直接查）")
        for name, label in [("糖尿病", "Disease"), ("哮喘", "Disease"), ("人参", "Herb")]:
            r = c.get("/api/graph/node", params={"name": name, "label": label})
            if r.status_code != 200:
                print(f"  {name:<8} HTTP {r.status_code}")
                continue
            d = r.json()
            print(f"  {name:<8} -> {d.get('name')}"
                  f"（{d.get('alias_zh') or '无别名'}）邻居 {d.get('neighbor_count')}")

        print("\n== 语义检索（中文病名走向量）")
        overview = c.get("/api/graph/overview").json()
        print(f"  索引文档 {overview['stats']['nodes']} 节点")

        r = c.post(
            "/api/chat",
            json={"question": "糖尿病能用哪些中药治疗？", "use_cache": False},
        ).json()
        print(f"  问答意图 {r['intent']}，证据 {len(r['evidence'])} 条")
        print(f"  Cypher: {(r['cypher'] or '（空）')[:110]}")
        print(f"  回答: {r['answer'][:80]}".replace("\n", " "))


if __name__ == "__main__":
    main()
