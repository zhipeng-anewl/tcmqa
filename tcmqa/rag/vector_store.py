# -*- coding: utf-8 -*-
"""进程内向量索引。

1.4 万条 × 512 维的点积在 CPU 上是毫秒级，所以这里就用最朴素的暴力检索，
不引 FAISS/Milvus——**数据量决定技术选型**，这个量级上向量库带来的复杂度
远大于收益。真要到百万级再换 HNSW，换的时候只需要替换本文件的 search。

持久化用 npz（矩阵）+ jsonl（元数据），好处是可读、可 diff、不依赖 pickle 协议。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tcmqa.rag.corpus import Document


@dataclass
class ScoredDoc:
    doc: Document
    score: float
    source: str  # vector | bm25 | both

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.doc.id,
            "kind": self.doc.kind,
            "title": self.doc.title,
            "text": self.doc.text,
            "score": round(self.score, 4),
            "source": self.source,
        }


class VectorStore:
    def __init__(self) -> None:
        self.docs: list[Document] = []
        self.matrix: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.docs)

    # ------------------------------------------------------------------ #
    def build(self, docs: list[Document], vectors: np.ndarray) -> None:
        if len(docs) != len(vectors):
            raise ValueError(f"文档数({len(docs)})与向量数({len(vectors)})不一致")
        self.docs = docs
        self.matrix = np.asarray(vectors, dtype=np.float32)

    def search(self, query_vector: np.ndarray, k: int = 8) -> list[ScoredDoc]:
        if self.matrix is None or not self.docs:
            return []
        # 向量已归一化，点积即余弦相似度
        scores = self.matrix @ query_vector.astype(np.float32)
        k = min(k, len(scores))
        top_idx = np.argpartition(-scores, k - 1)[:k]
        top_idx = top_idx[np.argsort(-scores[top_idx])]
        return [
            ScoredDoc(doc=self.docs[int(i)], score=float(scores[int(i)]), source="vector")
            for i in top_idx
        ]

    # ------------------------------------------------------------------ #
    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        if self.matrix is None:
            raise ValueError("向量索引为空，无法保存")
        np.save(directory / "vectors.npy", self.matrix)
        with (directory / "corpus.jsonl").open("w", encoding="utf-8") as f:
            for doc in self.docs:
                f.write(json.dumps(doc.to_dict(), ensure_ascii=False) + "\n")

    def load(self, directory: Path) -> None:
        matrix_path = directory / "vectors.npy"
        corpus_file = directory / "corpus.jsonl"
        if not matrix_path.exists() or not corpus_file.exists():
            raise FileNotFoundError(f"索引不存在：{directory}，请先运行 scripts/build_index.py")
        self.matrix = np.load(matrix_path)
        docs: list[Document] = []
        with corpus_file.open("r", encoding="utf-8") as f:
            for line in f:
                raw = json.loads(line)
                docs.append(
                    Document(
                        id=raw["id"],
                        kind=raw["kind"],
                        title=raw["title"],
                        text=raw["text"],
                        meta=raw.get("meta") or {},
                    )
                )
        self.docs = docs
