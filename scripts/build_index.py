# -*- coding: utf-8 -*-
"""构建语义检索索引：图谱 → 语料 → 向量 + BM25。

用法：
    python scripts/build_index.py                 # 中药 + 功效 + 疾病（约 1400 篇）
    python scripts/build_index.py --ingredients   # 额外索引 1.3 万个化学成分
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402
from tcmqa.logging import setup_logging  # noqa: E402
from tcmqa.rag.corpus import build_corpus  # noqa: E402
from tcmqa.rag.embedder import Embedder  # noqa: E402
from tcmqa.rag.vector_store import VectorStore  # noqa: E402
from tcmqa.settings import INDEX_DIR  # noqa: E402

logger = logging.getLogger("build_index")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingredients", action="store_true", help="是否索引全部化学成分")
    parser.add_argument("--out", default=str(INDEX_DIR))
    args = parser.parse_args()

    setup_logging("INFO")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    with GraphClient() as client:
        docs = build_corpus(client, include_ingredients=args.ingredients)
    logger.info("语料构建完成 %d 篇，用时 %.1fs", len(docs), time.perf_counter() - t0)

    kinds: dict[str, int] = {}
    for d in docs:
        kinds[d.kind] = kinds.get(d.kind, 0) + 1
    logger.info("分布：%s", json.dumps(kinds, ensure_ascii=False))

    embedder = Embedder()
    t0 = time.perf_counter()
    vectors = embedder.encode_documents([d.text for d in docs])
    logger.info(
        "向量化完成 shape=%s 用时 %.1fs", vectors.shape, time.perf_counter() - t0
    )

    store = VectorStore()
    store.build(docs, vectors)
    store.save(out_dir)
    logger.info("索引已保存到 %s", out_dir)

    meta = {
        "documents": len(docs),
        "kinds": kinds,
        "dim": int(vectors.shape[1]),
        "model": embedder.settings.embedding_model,
        "include_ingredients": args.ingredients,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
