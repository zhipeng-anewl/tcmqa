# -*- coding: utf-8 -*-
"""多模态检索接口：以图搜药、以文搜图。

两个入口，同一个索引：
- `POST /api/vision/search-image` 上传照片 → 最像的 N 味中药；
- `GET  /api/vision/search-text`  中文描述 → 最匹配的药材照片（跨模态，不是关键词匹配）。

接口不做「确诊」式的表述，返回的是**候选 + 相似度**，前端会明确标注这一点。
中医里很多药材外观相近（比如几种参类、几种柴胡），拿一张图断言是某味药是不负责任的。
"""

from __future__ import annotations

import io
import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from PIL import Image, UnidentifiedImageError

from tcmqa.api.deps import get_services

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vision", tags=["vision"])


def _serialize_hits(hits, query_type: str) -> dict[str, Any]:
    return {
        "query_type": query_type,
        "count": len(hits),
        "results": [
            {
                **hit.to_dict(),
                # 前端拿到就能直接发问，不必自己拼
                "followup": f"{hit.name}含有哪些化学成分？",
            }
            for hit in hits
        ],
        "disclaimer": "结果为视觉相似度候选，不构成药材鉴定结论；鉴别请咨询执业药师。",
    }


@router.post("/search-image")
async def search_image(
    request: Request,
    file: UploadFile = File(..., description="药材照片，jpg/png/webp，≤8MB"),
    top_k: int = Query(8, ge=1, le=20),
) -> dict[str, Any]:
    services = get_services(request.app)
    vision = services.vision

    if not vision.ready:
        raise HTTPException(
            status_code=503,
            detail="图像索引未构建，请先运行 python scripts/build_vision_index.py",
        )

    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"只接受图片，收到：{file.content_type}")

    limit_bytes = services.settings.vision_max_upload_mb * 1024 * 1024
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > limit_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"图片过大（{len(data) / 1024 / 1024:.1f}MB），上限 "
                   f"{services.settings.vision_max_upload_mb}MB",
        )

    # 先确认真的是图片，避免把任意二进制喂给模型
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"无法解析为图片：{exc}") from exc

    try:
        hits = vision.search_image_bytes(data, top_k=top_k)
    except Exception as exc:  # noqa: BLE001
        logger.exception("图像检索失败")
        raise HTTPException(status_code=500, detail=f"图像检索失败：{exc}") from exc

    return _serialize_hits(hits, "image")


@router.get("/search-text")
def search_text(
    request: Request,
    q: str = Query(..., min_length=1, max_length=100, description="中文描述，如「红色的果实」"),
    top_k: int = Query(8, ge=1, le=20),
    alpha: float | None = Query(
        None, ge=0.0, le=1.0,
        description="实体文本先验权重；不传则用配置值（0.5）。0=纯跨模态，1=纯文本",
    ),
) -> dict[str, Any]:
    services = get_services(request.app)
    vision = services.vision

    if not vision.ready:
        raise HTTPException(
            status_code=503,
            detail="图像索引未构建，请先运行 python scripts/build_vision_index.py",
        )

    try:
        hits = vision.search_text(q, top_k=top_k, alpha=alpha)
    except Exception as exc:  # noqa: BLE001
        logger.exception("文本检索失败")
        raise HTTPException(status_code=500, detail=f"文本检索失败：{exc}") from exc

    payload = _serialize_hits(hits, "text")
    payload["query"] = q
    payload["alpha"] = services.settings.vision_text_alpha if alpha is None else alpha
    return payload


@router.get("/stats")
def stats(request: Request) -> dict[str, Any]:
    services = get_services(request.app)
    vision = services.vision
    index = vision.index
    return {
        "ready": vision.ready,
        "images": len(index),
        "herbs": index.herb_count,
        "dim": int(index.matrix.shape[1]) if index.matrix is not None else 0,
        "has_text_prior": index.herb_text_matrix is not None,
        "text_alpha": services.settings.vision_text_alpha,
        "model": services.settings.clip_model,
        "index_dir": str(vision.index_dir),
    }
