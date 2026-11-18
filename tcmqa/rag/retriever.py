# -*- coding: utf-8 -*-
"""语义检索器：向量 + BM25 双路召回，RRF 融合。"""

from __future__ import annotations

import logging
from pathlib import Path

from tcmqa.rag.bm25_store import BM25Store, FusedDoc, rrf_fuse
from tcmqa.rag.corpus import Document
from tcmqa.rag.embedder import Embedder
from tcmqa.rag.vector_store import ScoredDoc, VectorStore
from tcmqa.settings import INDEX_DIR, Settings, get_settings

logger = logging.getLogger(__name__)


class SemanticRetriever:
    def __init__(
        self,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
        index_dir: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder or Embedder(self.settings)
        self.index_dir = index_dir or INDEX_DIR
        self.vector = VectorStore()
        self.bm25 = BM25Store()
        self._ready = False

    # ------------------------------------------------------------------ #
    @property
    def ready(self) -> bool:
        return self._ready

    def load(self) -> None:
        self.vector.load(self.index_dir)
        self.bm25.build(self.vector.docs)
        self._ready = True
        logger.info("语义索引加载完成：%d 篇文档", len(self.vector))

    # ------------------------------------------------------------------ #
    def search(self, query: str, top_k: int | None = None) -> list[FusedDoc]:
        if not self._ready:
            self.load()
        top_k = top_k or self.settings.fuse_top_k

        query_vector = self.embedder.encode_query(query)
        vector_hits = self.vector.search(query_vector, k=self.settings.vector_top_k)
        bm25_hits = self.bm25.search(query, k=self.settings.bm25_top_k)

        fused = rrf_fuse(
            {"vector": vector_hits, "bm25": bm25_hits},
            k=self.settings.rrf_k,
            top_n=top_k,
        )
        logger.info(
            "语义检索 query=%r vector=%d bm25=%d fused=%d",
            query[:40], len(vector_hits), len(bm25_hits), len(fused),
        )
        return fused

    def debug_sources(self, query: str) -> dict[str, list[dict]]:
        """给前端/评测看每一路召回了什么。"""
        if not self._ready:
            self.load()
        vector_hits: list[ScoredDoc] = self.vector.search(
            self.embedder.encode_query(query), k=self.settings.vector_top_k
        )
        bm25_hits = self.bm25.search(query, k=self.settings.bm25_top_k)
        return {
            "vector": [h.to_dict() for h in vector_hits],
            "bm25": [h.to_dict() for h in bm25_hits],
        }

    def docs_by_id(self, doc_id: str) -> Document | None:
        for doc in self.vector.docs:
            if doc.id == doc_id:
                return doc
        return None
