# -*- coding: utf-8 -*-
"""中文向量化封装。

选 BAAI/bge-small-zh-v1.5 的理由：512 维、约 25M 参数、CPU 可跑、中文检索效果好，
对 1.4 万篇文档的量级完全够用。用 sentence-transformers 只是为了省事，
换成本地 ONNX 或 API 只需要改这个文件。

两个容易踩的坑：
1. bge 系列做检索要区分查询和文档，查询端加指令前缀，文档端不加，否则效果变差；
2. 一定要 normalize，之后余弦相似度就退化成点积，检索时省一次除法。
"""

from __future__ import annotations

import os
from typing import Sequence

import numpy as np

from tcmqa.settings import Settings, get_settings


class Embedder:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._model = None

        # 必须在 import sentence_transformers 之前设，huggingface_hub 读的是环境变量
        os.environ.setdefault("HF_HOME", self.settings.hf_home)
        os.environ.setdefault("HF_ENDPOINT", self.settings.hf_endpoint)
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    # ------------------------------------------------------------------ #
    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            kwargs = {"device": self.settings.embedding_device}
            try:
                self._model = SentenceTransformer(
                    self.settings.embedding_model, local_files_only=True, **kwargs
                )
            except Exception:  # noqa: BLE001 - 本地没有就联网拉一次
                self._model = SentenceTransformer(self.settings.embedding_model, **kwargs)
        return self._model

    @property
    def dim(self) -> int:
        return int(self.model.get_sentence_embedding_dimension())

    # ------------------------------------------------------------------ #
    def encode_documents(self, texts: Sequence[str], batch_size: int | None = None) -> np.ndarray:
        vectors = self.model.encode(
            list(texts),
            batch_size=batch_size or self.settings.embedding_batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(vectors, dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        vector = self.model.encode(
            [self.settings.embedding_query_prefix + text],
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(vector[0], dtype=np.float32)
