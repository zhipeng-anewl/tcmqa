# -*- coding: utf-8 -*-
"""应用级单例容器。

FastAPI 里不要把 driver / 模型这种重资源放在每次请求里新建，
统一在 lifespan 里构建一次，挂到 app.state 上。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from tcmqa.kg.client import GraphClient
from tcmqa.kg.linker import EntityLinker
from tcmqa.llm.client import LLMClient
from tcmqa.rag.pipeline import QAPipeline
from tcmqa.rag.retriever import SemanticRetriever
from tcmqa.settings import Settings, get_settings
from tcmqa.store.sqlite import Database
from tcmqa.vision.retriever import VisionRetriever

logger = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    llm: LLMClient
    graph: GraphClient
    linker: EntityLinker
    semantic: SemanticRetriever
    vision: VisionRetriever
    db: Database
    pipeline: QAPipeline

    def close(self) -> None:
        for closer in (self.llm.close, self.graph.close, self.db.close):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass


def _warm_embedder(semantic: SemanticRetriever) -> None:
    """后台预热 embedding 模型。

    模型首次加载要几十秒（含权重转换）。如果在第一个用户请求里加载，
    那一位用户就要多等十几秒；放后台线程里加载，服务可以立刻对外可用，
    代价只是头几秒的请求仍然慢。
    """
    try:
        semantic.embedder.encode_query("预热")
        logger.info("embedding 模型预热完成")
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding 预热失败（不影响启动）：%s", exc)


def _warm_vision(vision: VisionRetriever) -> None:
    """后台预热 Chinese-CLIP。模型约 700MB，加载要十几秒，不能放在首个请求里。"""
    try:
        vision.encoder.embed_texts(["预热"])
        logger.info("Chinese-CLIP 预热完成")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chinese-CLIP 预热失败（图像检索不可用，其余功能不受影响）：%s", exc)


def build_services(settings: Settings | None = None, warm: bool = True) -> Services:
    settings = settings or get_settings()

    graph = GraphClient(settings)
    linker = EntityLinker(graph)
    linker.load()

    llm = LLMClient(settings)
    semantic = SemanticRetriever(settings)
    if warm:
        semantic.load()
        threading.Thread(target=_warm_embedder, args=(semantic,), daemon=True).start()

    # 图像索引只加载向量矩阵（几 MB），模型在后台线程里单独预热
    vision = VisionRetriever(settings)
    vision_ready = vision.load()
    if warm and vision_ready:
        threading.Thread(target=_warm_vision, args=(vision,), daemon=True).start()

    db = Database(settings.sqlite_path)
    pipeline = QAPipeline(llm, graph, linker, semantic, db, settings)

    return Services(
        settings=settings,
        llm=llm,
        graph=graph,
        linker=linker,
        semantic=semantic,
        vision=vision,
        db=db,
        pipeline=pipeline,
    )


def get_services(app: Any) -> Services:
    return app.state.services
