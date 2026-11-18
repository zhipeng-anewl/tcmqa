# -*- coding: utf-8 -*-
"""评测跨模态的文本→图像检索：用中药名当查询，看能不能召回到自己的照片。

这是检验「图文是否真的落在同一空间」的最直接方法。
如果连药名都召不回来，那自由描述（「红色的果实」）就更不可信。

用法：
    python scripts/eval_vision_text.py
    python scripts/eval_vision_text.py --samples 200
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
    parser.add_argument("--samples", type=int, default=150, help="抽样多少味药")
    parser.add_argument("--alpha", type=float, default=0.5,
                        help="文本融合权重：0=纯跨模态，0.5=图文各半，1=纯文本")
    parser.add_argument("--sweep", action="store_true", help="自动扫一遍 alpha 做对比")
    parser.add_argument("--out", default="data/vision_text_eval.json")
    args = parser.parse_args()

    setup_logging("WARNING")
    settings = get_settings()

    index = VisionIndex()
    index.load(Path(settings.vision_index_dir))
    print(f"索引: {len(index)} 张图 / {index.herb_count} 味药")
    print(f"文本先验: {'已加载' if index.herb_text_matrix is not None else '未构建（alpha 不生效）'}")

    herbs: dict[str, str] = {}
    for entry in index.entries:
        herbs.setdefault(entry.herb_id, entry.name)
    items = list(herbs.items())
    if args.samples and len(items) > args.samples:
        step = max(1, len(items) // args.samples)
        items = items[::step][: args.samples]
    print(f"文本查询样本 {len(items)} 条")

    encoder = ClipEncoder(settings)
    names = [n for _, n in items]
    started = time.perf_counter()
    vectors = encoder.embed_texts(names)
    elapsed = time.perf_counter() - started

    def evaluate(alpha: float) -> dict:
        hits_at = {1: 0, 3: 0, TOPK: 0}
        mrr = 0.0
        fails: list[dict] = []
        for (herb_id, name), vec in zip(items, vectors):
            results = index.search_text(vec, k=TOPK, alpha=alpha)
            ids = [r.herb_id for r in results]
            rank = ids.index(herb_id) + 1 if herb_id in ids else 0
            if rank == 1:
                hits_at[1] += 1
            if 0 < rank <= 3:
                hits_at[3] += 1
            if 0 < rank <= TOPK:
                hits_at[TOPK] += 1
            if rank:
                mrr += 1.0 / rank
            elif len(fails) < 8:
                fails.append({"query": name, "predicted": [r.name for r in results[:3]]})
        total = max(len(items), 1)
        return {
            "alpha": alpha,
            "queries": len(items),
            "top1": round(hits_at[1] / total, 4),
            "top3": round(hits_at[3] / total, 4),
            "top5": round(hits_at[TOPK] / total, 4),
            "mrr": round(mrr / total, 4),
            "failed_examples": fails,
        }

    alphas = [0.0, 0.3, 0.5, 0.7, 1.0] if args.sweep else [args.alpha]
    reports = []
    print()
    print(f"{'alpha':>6} {'Top-1':>8} {'Top-3':>8} {'Top-5':>8} {'MRR':>7}")
    for a in alphas:
        rep = evaluate(a)
        reports.append(rep)
        print(f"{a:>6.1f} {rep['top1']:>8.1%} {rep['top3']:>8.1%} "
              f"{rep['top5']:>8.1%} {rep['mrr']:>7.3f}")

    best = max(reports, key=lambda r: r["mrr"])
    summary = {
        "queries": len(items),
        "herbs_indexed": index.herb_count,
        "model": settings.clip_model,
        "has_text_prior": index.herb_text_matrix is not None,
        "encode_seconds": round(elapsed, 2),
        "sweep": reports,
        "best_alpha": best["alpha"],
        "best": {k: v for k, v in best.items() if k != "failed_examples"},
        "failed_examples": best["failed_examples"],
    }
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if best["failed_examples"]:
        print(f"\nalpha={best['alpha']} 下的失败样例（前 5）:")
        for f in best["failed_examples"][:5]:
            print(f"  「{f['query']}」 → 猜成 {f['predicted']}")


if __name__ == "__main__":
    main()
