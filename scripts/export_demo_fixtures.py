# -*- coding: utf-8 -*-
"""把真实问答录成静态 fixture，供「演示版」前端回放。

思路：直接录 `/api/chat/stream` 的 SSE 事件流，原样存下来。
回放时把事件按原顺序喂给前端的 handleEvent，行为和真实问答完全一致，
不用在前端重新定义一遍响应结构（也就不会对不上）。

连续的一串 token 事件会合并成一条完整文本，回放时再切碎做打字机效果，
这样单个 fixture 从几百 KB 降到几十 KB。

用法：
    python scripts/export_demo_fixtures.py
产物：
    frontend/public/demo/index.json          问题清单（含意图、耗时）
    frontend/public/demo/qa/q01.json …       每条问答的事件流
    frontend/public/demo/overview.json       首页统计
    frontend/public/demo/vision-stats.json   识药页统计
    frontend/public/demo/metrics.json        指标页快照
    frontend/public/demo/node/*.json         几个实体的检索结果（图谱页搜索用）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "demo"

# 覆盖全部意图与边界情况：属性查询、关系、聚合、机制、语义、
# 中文病名、多实体、越界拒绝、闲聊、成分反查
QUESTIONS = [
    "人参有哪些化学成分？",
    "为什么麻黄能治疗哮喘？",
    "有哪些清热解毒的中药？",
    "治疗乳腺癌的中药有多少味？",
    "黄芪有什么功效？",
    "手脚冰凉适合吃什么中药？",
    "枸杞子含有哪些化学成分？",
    "槲皮素作用于哪些靶点？",
    "糖尿病能用哪些中药？",
    "麻黄和桂枝有什么共同成分？",
    "大黄的性味归经是什么？",
    "川芎嗪是哪个中药的成分？",
    "当归的 ADME 参数有哪些？",
    "给我开个治失眠的药方",
    "今天天气怎么样？",
    "你好",
]

# 图谱页搜索框可查的实体（演示版只开放这几个）
NODES = [
    ("人参", "Herb"),
    ("麻黄", "Herb"),
    ("枸杞子", "Herb"),
    ("糖尿病", "Disease"),
    ("槲皮素", "Ingredient"),
]

# 识药页的文本检索演示
VISION_TEXT_QUERIES = ["红色的果实", "根茎类药材"]


def merge_tokens(events: list[dict]) -> list[dict]:
    """把连续 token 合并成一条，压缩体积；回放时再切碎。"""
    merged: list[dict] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            merged.append({"type": "token", "data": "".join(buf)})
            buf.clear()

    for ev in events:
        if ev.get("type") == "token":
            buf.append(ev.get("data") or "")
        else:
            flush()
            merged.append(ev)
    flush()
    return merged


def collect_stream(client: httpx.Client, question: str) -> list[dict]:
    events: list[dict] = []
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"question": question, "use_cache": True},
        timeout=180.0,
    ) as resp:
        resp.raise_for_status()
        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                raw, buffer = buffer.split("\n\n", 1)
                for line in raw.splitlines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        events.append(json.loads(line[5:].strip()))
                    except json.JSONDecodeError:
                        pass
    return events


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "qa").mkdir(exist_ok=True)
    (OUT / "node").mkdir(exist_ok=True)

    index: list[dict] = []
    with httpx.Client(base_url=BASE, timeout=180.0) as client:
        # ---- 静态快照 ----
        for name, path in [
            ("overview", "/api/graph/overview"),
            ("vision-stats", "/api/vision/stats"),
            ("metrics", "/api/metrics"),
        ]:
            try:
                data = client.get(path).json()
                write_json(OUT / f"{name}.json", data)
                print(f"[静态] {name:14s} OK")
            except Exception as exc:  # noqa: BLE001
                print(f"[静态] {name:14s} 失败：{exc}")

        # ---- 问答 ----
        for i, question in enumerate(QUESTIONS, start=1):
            slug = f"q{i:02d}"
            try:
                events = merge_tokens(collect_stream(client, question))
                write_json(OUT / "qa" / f"{slug}.json", events)

                plan = next((e.get("data") for e in events if e.get("type") == "plan"), {}) or {}
                done = next((e.get("data") for e in events if e.get("type") == "done"), {}) or {}
                index.append(
                    {
                        "id": slug,
                        "question": question,
                        "intent": plan.get("intent", ""),
                        "latency_ms": done.get("latency_ms"),
                        "tokens": (done.get("trace") or {}).get("total_tokens"),
                    }
                )
                print(f"[问答] {slug} {question}  -> {plan.get('intent', '?'):10s} {len(events)} 事件")
            except Exception as exc:  # noqa: BLE001
                print(f"[问答] {slug} {question}  失败：{exc}")

        # ---- 图谱节点 ----
        for name, label in NODES:
            try:
                detail = client.get(
                    "/api/graph/node", params={"name": name, "label": label}
                ).json()
                write_json(OUT / "node" / f"{name}.json", detail)
                print(f"[节点] {name:8s} {detail.get('neighbor_count')} 个邻居")
            except Exception as exc:  # noqa: BLE001
                print(f"[节点] {name:8s} 失败：{exc}")

        # ---- 识药文本检索 ----
        for i, q in enumerate(VISION_TEXT_QUERIES, start=1):
            try:
                data = client.get("/api/vision/search-text", params={"q": q, "top_k": 8}).json()
                write_json(OUT / "vision" / f"t{i}.json", data)
                print(f"[识药] {q:10s} {len(data.get('results', []))} 个候选")
            except Exception as exc:  # noqa: BLE001
                print(f"[识药] {q:10s} 失败：{exc}")

    write_json(OUT / "index.json", {"questions": index})
    total = sum(f.stat().st_size for f in OUT.rglob("*.json"))
    print(f"\n完成：{len(index)} 条问答，合计 {total / 1024:.0f} KB → {OUT}")


if __name__ == "__main__":
    main()
