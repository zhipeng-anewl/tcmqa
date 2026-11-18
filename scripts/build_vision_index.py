# -*- coding: utf-8 -*-
"""构建图像向量索引（以图搜药 / 文搜图的基础）。

索引的是**每味药的全部照片**（2,876 张 200px 缩略图），不是一张封面。
编码在 CPU 上约 7 张/秒，全量约 7 分钟，一次构建、长期复用。

用法：
    python scripts/build_vision_index.py
    python scripts/build_vision_index.py --limit 200   # 小规模验证
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402
from tcmqa.logging import setup_logging  # noqa: E402
from tcmqa.settings import get_settings  # noqa: E402
from tcmqa.vision.encoder import ClipEncoder  # noqa: E402
from tcmqa.vision.index import ImageEntry, VisionIndex  # noqa: E402

NAME_RE = re.compile(r"^(?P<herb>HER\d{4})_(?P<idx>\d+)$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="最多编码多少张（调试用）")
    parser.add_argument("--batch", type=int, default=16)
    args = parser.parse_args()

    setup_logging("WARNING")
    settings = get_settings()

    gallery_dir = Path(settings.media_dir) / "herb_gallery"
    if not gallery_dir.is_dir():
        print("缩略图目录不存在，请先运行 scripts/build_images.py")
        sys.exit(1)

    with GraphClient() as client:
        herbs = client.read(
            "MATCH (h:Herb) RETURN h.id AS id, h.name AS name, h.effect AS effect",
            limit=2000,
        )
    meta = {str(r["id"]): (str(r.get("name") or ""), str(r.get("effect") or "")) for r in herbs}

    # 按 (药编号, 图序号) 排序，保证索引顺序稳定
    files: list[tuple[Path, str, int]] = []
    for path in gallery_dir.glob("*.webp"):
        m = NAME_RE.match(path.stem)
        if not m:
            continue
        herb_id = m.group("herb")
        if herb_id not in meta:
            continue
        files.append((path, herb_id, int(m.group("idx"))))
    files.sort(key=lambda t: (t[1], t[2]))

    if args.limit:
        files = files[: args.limit]

    # 先验一遍图：坏图在编码阶段被跳过会导致条目与向量错位，不如提前剔除
    from PIL import Image  # noqa: E402

    valid: list[tuple[Path, str, int]] = []
    broken: list[str] = []
    for path, herb_id, idx in files:
        try:
            with Image.open(path) as probe:
                probe.verify()
            valid.append((path, herb_id, idx))
        except Exception:  # noqa: BLE001
            broken.append(path.name)
    if broken:
        print(f"跳过无法读取的图片 {len(broken)} 张：{broken[:5]}")
    files = valid

    per_herb: dict[str, int] = {}
    for _, herb_id, _idx in files:
        per_herb[herb_id] = per_herb.get(herb_id, 0) + 1

    entries = [
        ImageEntry(
            herb_id=herb_id,
            name=meta[herb_id][0],
            effect=meta[herb_id][1],
            image_index=idx,
            gallery=per_herb[herb_id],
        )
        for _, herb_id, idx in files
    ]
    paths = [p for p, _, _ in files]

    print(f"待编码 {len(entries)} 张，覆盖 {len(per_herb)} 味中药")

    encoder = ClipEncoder(settings)
    started = time.perf_counter()
    vectors = encoder.embed_images(paths, batch_size=args.batch)
    elapsed = time.perf_counter() - started
    print(f"编码完成 shape={vectors.shape} 用时 {elapsed:.1f}s "
          f"（{len(paths) / max(elapsed, 1e-6):.1f} 张/秒）")

    if len(vectors) != len(entries):
        print(f"错误：向量数 {len(vectors)} 与条目数 {len(entries)} 不一致，已中止")
        sys.exit(1)

    index = VisionIndex()
    index.build(entries, vectors)
    out = Path(settings.vision_index_dir)
    index.save(out)

    summary = {
        "images": len(index),
        "herbs": index.herb_count,
        "dim": int(vectors.shape[1]),
        "model": settings.clip_model,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "encode_seconds": round(elapsed, 1),
        "images_per_second": round(len(paths) / max(elapsed, 1e-6), 1),
    }
    (out / "meta.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"索引已保存 → {out}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
