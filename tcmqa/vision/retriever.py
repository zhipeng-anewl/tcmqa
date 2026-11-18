# -*- coding: utf-8 -*-
"""多模态检索器：以图搜药、以文搜图。

两条入口共用同一套图像向量索引——
查询是图片就过图像塔，查询是文字就过文本塔，最后都在图像向量空间里比相似度。
这是跨模态检索的关键：不是「拿文字去比文字」。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from tcmqa.settings import Settings, get_settings
from tcmqa.vision.encoder import ClipEncoder
from tcmqa.vision.index import ImageEntry, VisionHit, VisionIndex

logger = logging.getLogger(__name__)


class VisionRetriever:
    def __init__(
        self,
        settings: Settings | None = None,
        encoder: ClipEncoder | None = None,
        index_dir: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.encoder = encoder or ClipEncoder(self.settings)
        self.index_dir = Path(index_dir or self.settings.vision_index_dir)
        self.index = VisionIndex()
        self._loaded = False

    # ------------------------------------------------------------------ #
    @property
    def ready(self) -> bool:
        return self._loaded and self.index.ready

    def load(self, force: bool = False) -> bool:
        if self._loaded and not force:
            return True
        try:
            self.index.load(self.index_dir)
            self._loaded = True
            logger.info(
                "图像索引加载完成：%d 张图 / %d 味中药", len(self.index), self.index.herb_count
            )
            return True
        except FileNotFoundError as exc:
            logger.warning("%s", exc)
            return False

    # ------------------------------------------------------------------ #
    def search_image_bytes(self, data: bytes, top_k: int | None = None) -> list[VisionHit]:
        if not self.ready:
            return []
        vector = self.encoder.embed_bytes(data)
        return self.index.search(vector, k=top_k or self.settings.vision_top_k)

    def search_image_path(self, path: Path | str, top_k: int | None = None) -> list[VisionHit]:
        if not self.ready:
            return []
        vectors = self.encoder.embed_images([path])
        if len(vectors) == 0:
            return []
        return self.index.search(vectors[0], k=top_k or self.settings.vision_top_k)

    def search_text(
        self, text: str, top_k: int | None = None, alpha: float | None = None
    ) -> list[VisionHit]:
        if not self.ready:
            return []
        vector = self.encoder.embed_texts([text])[0]
        return self.index.search_text(
            vector,
            k=top_k or self.settings.vision_top_k,
            alpha=self.settings.vision_text_alpha if alpha is None else alpha,
        )

    # ------------------------------------------------------------------ #
    def items(self) -> Sequence[ImageEntry]:
        return self.index.entries
