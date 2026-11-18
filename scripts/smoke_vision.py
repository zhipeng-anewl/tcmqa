# -*- coding: utf-8 -*-
"""多模态检索冒烟：以文搜图、以图搜药是否正常（用真实索引）。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.logging import setup_logging  # noqa: E402
from tcmqa.settings import get_settings  # noqa: E402
from tcmqa.vision.encoder import ClipEncoder  # noqa: E402
from tcmqa.vision.index import VisionIndex  # noqa: E402


def main() -> None:
    setup_logging("WARNING")
    settings = get_settings()

    index = VisionIndex()
    index.load(Path(settings.vision_index_dir))
    print(f"索引: {len(index)} 张图 / {index.herb_count} 味药\n")

    encoder = ClipEncoder(settings)

    print("=== 以文搜图（自由描述）===")
    for query in [
        "人参",
        "麻黄",
        "红色的果实",
        "干燥的绿色草质茎叶",
        "白色的根茎切片",
    ]:
        t0 = time.perf_counter()
        vec = encoder.embed_texts([query])[0]
        hits = index.search(vec, k=5)
        ms = (time.perf_counter() - t0) * 1000
        line = "  ".join(f"{h.name}({h.score:.3f})" for h in hits)
        print(f"{query:<14} [{ms:>5.0f}ms] -> {line}")

    print("\n=== 以图搜药（拿某味药的第 2 张图去查）===")
    gallery = Path(settings.media_dir) / "herb_gallery"
    for herb_id in ["HER0336", "HER0264", "HER0002"]:
        q = gallery / f"{herb_id}_1.webp"
        if not q.exists():
            continue
        true_name = next((e.name for e in index.entries if e.herb_id == herb_id), herb_id)
        t0 = time.perf_counter()
        vec = encoder.embed_images([q], batch_size=1)[0]
        hits = index.search(vec, k=5, exclude=(herb_id, 1))
        ms = (time.perf_counter() - t0) * 1000
        line = "  ".join(f"{h.name}({h.score:.3f})" for h in hits)
        print(f"{true_name}(第2张) [{ms:>5.0f}ms] -> {line}")


if __name__ == "__main__":
    main()
