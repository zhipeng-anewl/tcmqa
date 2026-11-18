# -*- coding: utf-8 -*-
"""对话相关接口：同步问答、SSE 流式问答、会话回放、反馈。"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from tcmqa.api.deps import get_services
from tcmqa.api.schemas import ChatRequest, ChatResponse, FeedbackRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

# 简单的并发闸门：超过上限就排队，避免几十个请求同时打 LLM 把额度打爆
_semaphore_lock = threading.Lock()
_semaphore: threading.Semaphore | None = None


def _get_semaphore(limit: int) -> threading.Semaphore:
    global _semaphore
    with _semaphore_lock:
        if _semaphore is None:
            _semaphore = threading.Semaphore(max(1, limit))
        return _semaphore


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    services = get_services(request.app)
    sem = _get_semaphore(services.settings.llm_max_concurrency)

    with sem:
        try:
            result = services.pipeline.answer(
                req.question, session_id=req.session_id, use_cache=req.use_cache
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("问答失败")
            raise HTTPException(status_code=500, detail=f"问答失败：{exc}") from exc

    return ChatResponse(**result.to_dict())


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """SSE 流式返回。

    事件序列：meta → plan → retrieval → evidence → token* → citations → done
    前端按 type 分发即可；出错时发一个 error 事件，不让连接静默断掉。
    """
    services = get_services(request.app)
    sem = _get_semaphore(services.settings.llm_max_concurrency)

    def event_stream() -> Iterator[str]:
        acquired = sem.acquire(timeout=60)
        try:
            if not acquired:
                yield _sse({"type": "error", "data": "系统繁忙，请稍后重试"})
                return
            for event in services.pipeline.stream(
                req.question, session_id=req.session_id, use_cache=req.use_cache
            ):
                yield _sse(event)
        except GeneratorExit:
            logger.info("客户端断开连接")
        except Exception as exc:  # noqa: BLE001
            logger.exception("流式问答失败")
            yield _sse({"type": "error", "data": f"问答失败：{exc}"})
        finally:
            if acquired:
                sem.release()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 下关闭缓冲，否则流式变成一次性返回
        },
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------- #
@router.get("/sessions")
def list_sessions(request: Request, limit: int = 30) -> list[dict[str, Any]]:
    return get_services(request.app).db.list_sessions(limit)


@router.get("/sessions/{session_id}/messages")
def session_messages(session_id: str, request: Request, limit: int = 50) -> list[dict[str, Any]]:
    return get_services(request.app).db.get_messages(session_id, limit)


# ---------------------------------------------------------------------- #
@router.post("/feedback")
def feedback(req: FeedbackRequest, request: Request) -> dict[str, Any]:
    db = get_services(request.app).db
    db.add_feedback(req.trace_id, req.rating, req.comment)
    return {"ok": True, "stats": db.feedback_stats()}


@router.get("/feedback/stats")
def feedback_stats(request: Request) -> dict[str, Any]:
    return get_services(request.app).db.feedback_stats()
