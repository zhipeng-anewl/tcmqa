# -*- coding: utf-8 -*-
"""为每味药生成「药名，功效」的文本向量，补上文本查询的实体先验。

背景：纯 CLIP 文本塔对药材名不敏感（实测「人参」这类查询 top-5 只有 40%），
因为它在描述性 caption 上训练，而药名更接近「命名」而不是「描述」。
给每味药预存一个文本向量后，查询时可以和图像分数加权融合。

这一步只需要编码 502 条短文本，几秒钟完成，不影响已有的图像索引。

用法：
    python scripts/build_vision_text.py --alpha 0.5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from tcmqa.logging import setup_logging  # noqa: E402
from tcmqa.settings import get_settings  # noqa: E402
from tcmqa.vision.encoder import ClipEncoder  # noqa: E402
from tcmqa.vision.index import VisionIndex  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=64)
    args = parser.parse_args()

    setup_logging("WARNING")
    settings = get_settings()

    index = VisionIndex()
    index.load(Path(settings.vision_index_dir))
    print(f"已加载图像索引：{len(index)} 张图 / {index.herb_count} 味药")

    # 每味药一条，取该药第一条记录的名称与功效
    seen: dict[str, tuple[str, str]] = {}
    for entry in index.entries:
        if entry.herb_id not in seen:
            seen[entry.herb_id] = (entry.name, entry.effect)

    herb_ids = list(seen.keys())
    texts = [f"{name}，{effect or '中药'}" for name, effect in (seen[h] for h in herb_ids)]
    print(f"编码 {len(texts)} 条药名文本，例如：{texts[:3]}")

    encoder = ClipEncoder(settings)
    started = time.perf_counter()
    vectors = encoder.embed_texts(texts)
    elapsed = time.perf_counter() - started
    print(f"完成 shape={vectors.shape} 用时 {elapsed:.1f}s")

    index.herb_ids = herb_ids
    index.herb_texts = texts
    index.herb_text_matrix = np.asarray(vectors, dtype=np.float32)
    index.save(Path(settings.vision_index_dir))

    meta_path = Path(settings.vision_index_dir) / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["herb_texts"] = len(texts)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已写入 {settings.vision_index_dir}")
    print("现在可以用 scripts/eval_vision_text.py --alpha 0.5 对比效果")


if __name__ == "__main__":
    main()
