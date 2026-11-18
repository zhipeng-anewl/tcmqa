# -*- coding: utf-8 -*-
"""图像向量索引。

两个和「一张封面代表一味药」不同的关键设计：

1. **每味药索引多张照片**（一共 2,876 张，平均 5.7 张/味），
   检索时按药聚合取最高分。只拿一张封面代表一味药，换个角度/光照就召不回来。
2. **索引里放的是 200px 缩略图**的向量，不是 1.13GB 的原图。
   CLIP 反正要把图缩到 224×224，用缩略图编码结果几乎一样，但读盘快几十倍。

查询既可以是图片（图像塔），也可以是文字（文本塔），两者都在同一个图像向量空间里比对——
这才是跨模态检索，而不是「拿文字比文字」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class ImageEntry:
    """索引里的一条：某味药的某张照片。"""

    herb_id: str
    name: str
    effect: str
    image_index: int  # 0 是封面
    gallery: int = 0  # 该药总图数

    def to_dict(self) -> dict[str, Any]:
        return {
            "herb_id": self.herb_id,
            "name": self.name,
            "effect": self.effect,
            "image_index": self.image_index,
            "gallery": self.gallery,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ImageEntry":
        return cls(
            herb_id=str(raw.get("herb_id") or ""),
            name=str(raw.get("name") or ""),
            effect=str(raw.get("effect") or ""),
            image_index=int(raw.get("image_index") or 0),
            gallery=int(raw.get("gallery") or 0),
        )


@dataclass
class VisionHit:
    herb_id: str
    name: str
    effect: str
    score: float
    matched_image: int = 0
    gallery: int = 0

    @property
    def cover(self) -> str:
        return f"/media/covers/{self.herb_id}.webp"

    def to_dict(self) -> dict[str, Any]:
        return {
            "herb_id": self.herb_id,
            "name": self.name,
            "effect": self.effect,
            "cover": self.cover,
            "gallery": self.gallery,
            "matched_image": self.matched_image,
            "score": round(self.score, 4),
        }


@dataclass
class VisionIndex:
    entries: list[ImageEntry] = field(default_factory=list)
    matrix: np.ndarray | None = None
    # 每味药「药名，功效」的文本向量，用于文本查询时补一个实体级先验
    herb_ids: list[str] = field(default_factory=list)
    herb_text_matrix: np.ndarray | None = None
    herb_texts: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        """返回索引里的图片数（不是药味数）。"""
        return len(self.entries)

    @property
    def herb_count(self) -> int:
        return len({e.herb_id for e in self.entries})

    @property
    def ready(self) -> bool:
        return self.matrix is not None and bool(self.entries)

    # ------------------------------------------------------------------ #
    def build(self, entries: list[ImageEntry], vectors: np.ndarray) -> None:
        if len(entries) != len(vectors):
            raise ValueError(f"条目数({len(entries)})与向量数({len(vectors)})不一致")
        self.entries = entries
        self.matrix = np.asarray(vectors, dtype=np.float32)

    def search(
        self,
        query_vector: np.ndarray,
        k: int = 8,
        exclude: tuple[str, int] | None = None,
    ) -> list[VisionHit]:
        """纯图像检索，按药聚合：一味药有多张图时取最高分那张。"""
        image_scores = self._herb_image_scores(query_vector, exclude)
        ranked = sorted(image_scores.items(), key=lambda kv: kv[1][0], reverse=True)[:k]
        return [self._to_hit(herb_id, score, idx) for herb_id, (score, idx) in ranked]

    def search_text(
        self,
        query_vector: np.ndarray,
        k: int = 8,
        alpha: float = 0.5,
    ) -> list[VisionHit]:
        """文本检索：图像相似度 + 实体文本相似度加权融合。

        纯 CLIP 的文本塔对「药材名」这类单实体标签不敏感（实测 top-5 只有 40%），
        因为它是在描述性 caption 上训练的，而「人参」这种词更接近命名而非描述。
        所以给每味药预存一个「药名，功效」的文本向量，查询时和图像分数加权：

            score = alpha * cos(查询, 药名+功效) + (1 - alpha) * max_i cos(查询, 图_i)

        alpha=0 退化为纯跨模态；alpha 越大越偏向实体名匹配。
        外观描述类查询（「红色的果实」）靠图像项，药名类查询靠文本项。
        """
        image_scores = self._herb_image_scores(query_vector, None)

        if (
            self.herb_text_matrix is None
            or not self.herb_ids
            or alpha <= 0
        ):
            ranked = sorted(image_scores.items(), key=lambda kv: kv[1][0], reverse=True)[:k]
            return [self._to_hit(h, s, i) for h, (s, i) in ranked]

        vec = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        text_scores = self.herb_text_matrix @ vec
        herb_pos = {h: i for i, h in enumerate(self.herb_ids)}

        combined: dict[str, tuple[float, int]] = {}
        for herb_id, (img_score, idx) in image_scores.items():
            pos = herb_pos.get(herb_id)
            txt_score = float(text_scores[pos]) if pos is not None else 0.0
            combined[herb_id] = (alpha * txt_score + (1 - alpha) * img_score, idx)

        ranked = sorted(combined.items(), key=lambda kv: kv[1][0], reverse=True)[:k]
        return [self._to_hit(h, s, i) for h, (s, i) in ranked]

    # ------------------------------------------------------------------ #
    def _herb_image_scores(
        self, query_vector: np.ndarray, exclude: tuple[str, int] | None
    ) -> dict[str, tuple[float, int]]:
        if not self.ready or self.matrix is None:
            return {}
        vec = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        scores = self.matrix @ vec
        best: dict[str, tuple[float, int]] = {}
        for idx, entry in enumerate(self.entries):
            if exclude is not None and (entry.herb_id, entry.image_index) == exclude:
                continue
            score = float(scores[idx])
            prev = best.get(entry.herb_id)
            if prev is None or score > prev[0]:
                best[entry.herb_id] = (score, idx)
        return best

    def _to_hit(self, herb_id: str, score: float, idx: int) -> VisionHit:
        entry = self.entries[idx]
        return VisionHit(
            herb_id=herb_id,
            name=entry.name,
            effect=entry.effect,
            score=score,
            matched_image=entry.image_index,
            gallery=entry.gallery,
        )

    # ------------------------------------------------------------------ #
    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        if self.matrix is None:
            raise ValueError("索引为空，无法保存")
        np.save(directory / "vision_vectors.npy", self.matrix)
        with (directory / "vision_items.json").open("w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.entries], f, ensure_ascii=False)

        if self.herb_text_matrix is not None:
            np.save(directory / "vision_text_vectors.npy", self.herb_text_matrix)
            with (directory / "vision_herbs.json").open("w", encoding="utf-8") as f:
                json.dump(
                    {"herb_ids": self.herb_ids, "texts": self.herb_texts},
                    f,
                    ensure_ascii=False,
                )

    def load(self, directory: Path) -> None:
        matrix_path = directory / "vision_vectors.npy"
        items_path = directory / "vision_items.json"
        if not matrix_path.exists() or not items_path.exists():
            raise FileNotFoundError(
                f"图像索引不存在：{directory}，请先运行 scripts/build_vision_index.py"
            )
        self.matrix = np.load(matrix_path)
        raw = json.loads(items_path.read_text(encoding="utf-8"))
        self.entries = [ImageEntry.from_dict(x) for x in raw]

        text_path = directory / "vision_text_vectors.npy"
        herbs_path = directory / "vision_herbs.json"
        if text_path.exists() and herbs_path.exists():
            self.herb_text_matrix = np.load(text_path)
            meta = json.loads(herbs_path.read_text(encoding="utf-8"))
            self.herb_ids = list(meta.get("herb_ids") or [])
            self.herb_texts = list(meta.get("texts") or [])
