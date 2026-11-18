# -*- coding: utf-8 -*-
"""复现「证据链」节点搜索：看接口返回什么，封面地址是否有效。"""

from __future__ import annotations

import sys

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=60.0) as c:
        found = c.get("/api/graph/search", params={"q": "枸杞", "limit": 8}).json()
        print("搜索命中:", found.get("results"))

        if not found.get("results"):
            return

        first = found["results"][0]
        detail = c.get(
            "/api/graph/node",
            params={"name": first["name"], "label": first["label"]},
        ).json()
        print(f"\n节点: {first['name']} ({first['label']}) id={first.get('id')}")
        print("邻居数:", detail.get("neighbor_count"))

        neighbors = detail.get("neighbors") or []
        print(f"返回邻居 {len(neighbors)} 条，前 6 条:")
        for n in neighbors[:6]:
            print("  ", n)

        # 邻居里有没有 name 为空的、label 缺失的
        bad = [n for n in neighbors if not n.get("name") or not n.get("label")]
        print("\n异常邻居（缺 name 或 label）:", len(bad))
        for n in bad[:5]:
            print("   ", n)

        # 封面
        if first.get("label") == "Herb":
            url = f"/media/covers/{first['id']}.webp"
            r = c.get(url)
            print(f"\n封面 {url} -> {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes")

        # 看一下 neighbor 里出现的所有 label
        labels = sorted({str(n.get("label")) for n in neighbors})
        print("邻居 label 集合:", labels)


if __name__ == "__main__":
    main()
