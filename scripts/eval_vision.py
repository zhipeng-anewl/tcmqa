# -*- coding: utf-8 -*-
"""图像检索的离线评测：leave-one-out。

评估方式：拿库里某张照片去检索，把它自己从候选里排除，看能不能召回**同一味药的其他照片**。
- 索引里每味药有多张图，查询时排除自身，不存在「自己匹配自己」的泄漏；
- 目标是「召回到同一味药」，这正是以图搜药要解决的问题。

指标：Top-1 / Top-3 / Top-5 命中率 + MRR。

用法：
    python scripts/eval_vision.py               # 全量（约 2,300 张查询）
    python scripts/eval_vision.py --limit 300   # 抽样
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.logging import setup_logging  # noqa: E402
from tcmqa.settings import get_settings  # noqa: E402
from tcmqa.vision.encoder import ClipEncoder  # noqa: E402
from tcmqa.vision.index import VisionIndex  # noqa: E402

TOPK = 5


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--out", default="data/vision_eval.json")
    args = parser.parse_args()

    setup_logging("WARNING")
    settings = get_settings()

    index = VisionIndex()
    index.load(Path(settings.vision_index_dir))
    print(f"索引: {len(index)} 张图 / {index.herb_count} 味药, dim={index.matrix.shape[1]}")

    gallery = Path(settings.media_dir) / "herb_gallery"

    # 只拿「非首图」当查询，保证检索目标至少还有别的图存在
    queries = []
    for entry in index.entries:
        if entry.image_index == 0:
            continue
        path = gallery / f"{entry.herb_id}_{entry.image_index}.webp"
        if path.exists():
            queries.append((path, entry.herb_id, entry.image_index))

    print(f"可用查询 {len(queries)} 张")
    if args.limit and len(queries) > args.limit:
        step = max(1, len(queries) // args.limit)
        queries = queries[::step][: args.limit]
        print(f"抽样后 {len(queries)} 张")

    encoder = ClipEncoder(settings)
    started = time.perf_counter()
    hits_at = {1: 0, 3: 0, TOPK: 0}
    mrr = 0.0
    processed = 0
    failures: list[dict] = []

    for start in range(0, len(queries), args.batch):
        chunk = queries[start : start + args.batch]
        vectors = encoder.embed_images([q[0] for q in chunk], batch_size=len(chunk))
        for (path, herb_id, img_idx), vec in zip(chunk, vectors):
            results = index.search(vec, k=TOPK, exclude=(herb_id, img_idx))
            names = [r.herb_id for r in results]
            rank = names.index(herb_id) + 1 if herb_id in names else 0
            processed += 1

            if rank == 1:
                hits_at[1] += 1
            if 0 < rank <= 3:
                hits_at[3] += 1
            if 0 < rank <= TOPK:
                hits_at[TOPK] += 1
            if rank:
                mrr += 1.0 / rank
            elif len(failures) < 10:
                failures.append(
                    {
                        "query": path.name,
                        "true": next(
                            (e.name for e in index.entries if e.herb_id == herb_id), herb_id
                        ),
                        "predicted": [r.name for r in results[:3]],
                    }
                )

        if (start // args.batch) % 20 == 0:
            print(f"  进度 {processed}/{len(queries)}", flush=True)

    elapsed = time.perf_counter() - started
    total = max(processed, 1)
    summary = {
        "queries": processed,
        "images_indexed": len(index),
        "herbs_indexed": index.herb_count,
        "model": settings.clip_model,
        "top1": round(hits_at[1] / total, 4),
        "top3": round(hits_at[3] / total, 4),
        "top5": round(hits_at[TOPK] / total, 4),
        "mrr": round(mrr / total, 4),
        "elapsed_sec": round(elapsed, 1),
        "failed_examples": failures,
    }

    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(f"查询 {processed} 张，用时 {elapsed:.1f}s")
    print(f"Top-1 命中率 {summary['top1']:.1%}")
    print(f"Top-3 命中率 {summary['top3']:.1%}")
    print(f"Top-5 命中率 {summary['top5']:.1%}")
    print(f"MRR {summary['mrr']:.3f}")
    if failures:
        print("\n失败样例（前 5）:")
        for f in failures[:5]:
            print(f"  {f['query']}: 实际 {f['true']} → 预测 {f['predicted']}")


if __name__ == "__main__":
    main()
