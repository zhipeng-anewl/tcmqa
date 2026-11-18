# -*- coding: utf-8 -*-
"""演示脚本：用最直白的方式调用接口，打印一次完整问答。"""

from __future__ import annotations

import json
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"


def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else "为什么麻黄能治疗哮喘？"

    with httpx.Client(base_url=BASE, timeout=180.0) as client:
        health = client.get("/api/health").json()
        print(f"服务状态: {health['status']}  图谱: {health['checks']['neo4j']['ok']}  "
              f"索引文档: {health['checks']['index']['documents']}")
        print("=" * 70)

        t0 = time.perf_counter()
        r = client.post("/api/chat", json={"question": question, "use_cache": False})
        r.raise_for_status()
        data = r.json()
        elapsed = (time.perf_counter() - t0) * 1000

        print(f"问题: {question}")
        print(f"意图: {data['intent']}   耗时: {elapsed:.0f}ms   "
              f"token: {data['trace']['total_tokens']}   成本: ¥{data['trace']['cost_cny']}")
        print("-" * 70)
        print("Cypher:")
        print("  " + (data["cypher"] or "(未走图谱)").replace("\n", "\n  "))
        print("-" * 70)
        print("证据:")
        for e in data["evidence"][:6]:
            print(f"  [{e['id']}] {e['text'][:88]}")
        print("-" * 70)
        print("回答:")
        for line in data["answer"].split("\n"):
            print("  " + line)
        print("-" * 70)
        print("分阶段耗时:", json.dumps(data["trace"]["stage_ms"], ensure_ascii=False))
        print("引用校验:", json.dumps(data["citations"], ensure_ascii=False))


if __name__ == "__main__":
    main()
