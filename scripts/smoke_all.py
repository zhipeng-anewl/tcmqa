# -*- coding: utf-8 -*-
"""重启后的整体自检：健康状态 + 图谱问答 + 多模态 + 图片。

用法：
    python scripts/smoke_all.py
"""

from __future__ import annotations

import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=240.0) as client:
        # ---- 1. 子系统 ----
        health = client.get("/api/health").json()
        print(f"[健康] {health['status']}")
        print(f"  Neo4j : {health['checks']['neo4j']['ok']}")
        print(f"  LLM   : {health['checks']['llm']['model']}   key={health['checks']['llm']['ok']}")
        print(f"  文本索引: {health['checks']['index']['documents']} 篇")

        vision = client.get("/api/vision/stats").json()
        print(f"  图像索引: {vision['images']} 张 / {vision['herbs']} 味 "
              f"({vision['model'].split('/')[-1]}, alpha={vision.get('text_alpha')})")

        media = client.get("/api/media/stats").json()
        print(f"  图片资源: 封面 {media['covers']['count']} 张, "
              f"结构式 {media['mol_source']['files']} 张")

        # ---- 2. 图谱问答 ----
        print("\n[问答]")
        t0 = time.perf_counter()
        r = client.post("/api/chat", json={"question": "人参含有哪些化学成分？", "use_cache": False})
        data = r.json()
        ms = (time.perf_counter() - t0) * 1000
        print(f"  意图 {data['intent']} | {ms:.0f}ms | 证据 {len(data['evidence'])} 条 | "
              f"token {data['trace']['total_tokens']} | 引用合法 {not data['citations'].get('has_invalid')}")
        print(f"  Cypher: {(data['cypher'] or '(未走图谱)')[:80]}")
        print(f"  回答: {data['answer'][:100]}".replace("\n", " "))

        # ---- 3. 多模态 ----
        print("\n[多模态]")
        for query in ["人参", "红色的果实"]:
            t0 = time.perf_counter()
            hits = client.get("/api/vision/search-text", params={"q": query, "top_k": 4}).json()
            ms = (time.perf_counter() - t0) * 1000
            names = "  ".join(x["name"] for x in hits["results"])
            print(f"  「{query}」 {ms:>5.0f}ms -> {names}")

        # ---- 4. 图片 ----
        print("\n[图片]")
        resolved = client.get("/api/media/resolve", params={"names": "人参,quercetin"}).json()
        for name, info in resolved["items"].items():
            resp = client.get(info["thumb"])
            print(f"  {name}: {resp.status_code} {resp.headers.get('content-type')} "
                  f"{len(resp.content) / 1024:.1f}KB")

        print("\n自检完成")


if __name__ == "__main__":
    main()
