# -*- coding: utf-8 -*-
"""多模态检索接口的端到端测试：状态、以文搜图、以图搜药（真实上传）。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=180.0)

    stats = client.get("/api/vision/stats").json()
    print("== 索引状态")
    print(json.dumps(stats, ensure_ascii=False))
    if not stats.get("ready"):
        print("索引未就绪，先跑 scripts/build_vision_index.py")
        return

    print("\n== 以文搜图")
    for q in ["人参", "红色的果实", "干燥的绿色草质茎叶", "麻黄"]:
        t0 = time.perf_counter()
        r = client.get("/api/vision/search-text", params={"q": q, "top_k": 5})
        ms = (time.perf_counter() - t0) * 1000
        data = r.json()
        line = "  ".join(f"{x['name']}({x['score']:.3f})" for x in data["results"])
        print(f"{q:<12} [{ms:>5.0f}ms] -> {line}")

    print("\n== 以图搜药（上传真实图片）")
    for herb_id, name in [("HER0336", "人参"), ("HER0264", "麻黄")]:
        img = ROOT / "data" / "images" / "herb_gallery" / f"{herb_id}_1.webp"
        if not img.exists():
            continue
        t0 = time.perf_counter()
        with img.open("rb") as f:
            r = client.post(
                "/api/vision/search-image",
                params={"top_k": 5},
                files={"file": (img.name, f, "image/webp")},
            )
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            print(f"{name}: HTTP {r.status_code} {r.text[:200]}")
            continue
        data = r.json()
        line = "  ".join(f"{x['name']}({x['score']:.3f})" for x in data["results"])
        print(f"{name}(第2张图) [{ms:>5.0f}ms] -> {line}")

    print("\n== 错误处理")
    r = client.post("/api/vision/search-image",
                    files={"file": ("x.txt", b"not an image", "text/plain")})
    print("非图片文件:", r.status_code, str(r.json().get("detail"))[:60])
    r = client.post("/api/vision/search-image",
                    files={"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png")})
    print("损坏图片:", r.status_code, str(r.json().get("detail"))[:50])

    client.close()


if __name__ == "__main__":
    main()
