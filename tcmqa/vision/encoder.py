# -*- coding: utf-8 -*-
"""中文多模态编码器（Chinese-CLIP）。

为什么用 Chinese-CLIP 而不是官方 CLIP：官方 CLIP 的文本塔几乎只认英文，
用户问「红色的果实」「干燥的根茎」这类中文描述时，文本向量和图像向量根本对不上。
Chinese-CLIP 用中文图文对训练，才可能让「人参」和人参照片落在邻近位置。

模型只在第一次用到时加载（约 700MB / CPU 上几秒），之后的编码是毫秒级。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from tcmqa.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class ClipEncoder:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._model = None
        self._processor = None
        self._torch = None

        # 必须在 import transformers 之前设，huggingface_hub 读环境变量
        os.environ.setdefault("HF_HOME", self.settings.hf_home)
        os.environ.setdefault("HF_ENDPOINT", self.settings.hf_endpoint)
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    # ------------------------------------------------------------------ #
    @property
    def model(self):
        if self._model is None:
            import torch
            from transformers import ChineseCLIPModel

            kwargs: dict[str, Any] = {}
            try:
                model = ChineseCLIPModel.from_pretrained(
                    self.settings.clip_model, local_files_only=True, **kwargs
                )
            except Exception:  # noqa: BLE001 - 本地没有就联网拉一次
                model = ChineseCLIPModel.from_pretrained(self.settings.clip_model, **kwargs)
            model.eval()
            self._torch = torch
            self._model = model
            logger.info("Chinese-CLIP 已加载：%s", self.settings.clip_model)
        return self._model

    @property
    def processor(self):
        if self._processor is None:
            from transformers import ChineseCLIPProcessor

            try:
                self._processor = ChineseCLIPProcessor.from_pretrained(
                    self.settings.clip_model, local_files_only=True
                )
            except Exception:  # noqa: BLE001
                self._processor = ChineseCLIPProcessor.from_pretrained(self.settings.clip_model)
        return self._processor

    @property
    def dim(self) -> int:
        return int(self.model.config.projection_dim)

    # ------------------------------------------------------------------ #
    def _image_features(self, pixel_values):
        """transformers 5.x 的 get_*_features 返回 BaseModelOutput 而不是张量，
        投影后的向量在 pooler_output 里（维度 = projection_dim）。"""
        torch = self._torch or __import__("torch")
        with torch.no_grad():
            if hasattr(self.model, "get_image_features"):
                out = self.model.get_image_features(pixel_values=pixel_values)
            else:  # 兜底：视觉塔 + 投影层
                out = self.model.vision_model(pixel_values=pixel_values)
        feats = getattr(out, "pooler_output", out)
        if not hasattr(feats, "norm"):
            feats = self.model.visual_projection(feats)
        return torch.nn.functional.normalize(feats, dim=-1)

    def _text_features(self, input_ids, attention_mask):
        torch = self._torch or __import__("torch")
        with torch.no_grad():
            if hasattr(self.model, "get_text_features"):
                out = self.model.get_text_features(
                    input_ids=input_ids, attention_mask=attention_mask
                )
            else:  # 兜底：文本塔 + 投影层
                out = self.model.text_model(
                    input_ids=input_ids, attention_mask=attention_mask
                )
        feats = getattr(out, "pooler_output", out)
        if not hasattr(feats, "norm"):
            feats = self.model.text_projection(feats)
        return torch.nn.functional.normalize(feats, dim=-1)

    # ------------------------------------------------------------------ #
    def embed_images(self, paths: Sequence[Path | str], batch_size: int = 16) -> np.ndarray:
        from PIL import Image

        rows: list[np.ndarray] = []
        batch: list[Any] = []

        for path in paths:
            try:
                batch.append(Image.open(path).convert("RGB"))
            except Exception as exc:  # noqa: BLE001 - 坏图不该拖垮整批
                logger.warning("跳过无法读取的图片 %s: %s", path, exc)
                continue
            if len(batch) >= batch_size:
                rows.append(self._encode_image_batch(batch))
                batch = []
        if batch:
            rows.append(self._encode_image_batch(batch))

        if not rows:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack(rows)

    def _encode_image_batch(self, images: list[Any]) -> np.ndarray:
        inputs = self.processor(images=images, return_tensors="pt")
        feats = self._image_features(inputs["pixel_values"])
        return feats.cpu().numpy().astype(np.float32)

    def embed_pil(self, images: list[Any]) -> np.ndarray:
        if not images:
            return np.zeros((0, self.dim), dtype=np.float32)
        return self._encode_image_batch([im.convert("RGB") for im in images])

    def embed_bytes(self, data: bytes) -> np.ndarray:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("RGB")
        return self._encode_image_batch([image])[0]

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        inputs = self.processor(
            text=list(texts), return_tensors="pt", padding=True, truncation=True, max_length=64
        )
        feats = self._text_features(inputs["input_ids"], inputs["attention_mask"])
        return feats.cpu().numpy().astype(np.float32)
