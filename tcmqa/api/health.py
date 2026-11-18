# -*- coding: utf-8 -*-
"""健康检查与运行指标。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

from tcmqa import __version__
from tcmqa.api.deps import get_services
from tcmqa.kg.client import GraphError

router = APIRouter(tags=["ops"])


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    services = get_services(request.app)
    started = time.perf_counter()

    neo4j_ok, neo4j_error = True, ""
    try:
        services.graph.scalar("RETURN 1 AS ok")
    except GraphError as exc:
        neo4j_ok, neo4j_error = False, str(exc)

    index_ok = services.semantic.ready
    payload = {
        "status": "ok" if (neo4j_ok and index_ok) else "degraded",
        "version": __version__,
        "checks": {
            "neo4j": {"ok": neo4j_ok, "error": neo4j_error},
            "llm": {"ok": bool(services.settings.deepseek_api_key),
                    "model": services.settings.llm_model},
            "index": {
                "ok": index_ok,
                "documents": len(services.semantic.vector),
                "model": services.settings.embedding_model,
            },
            "cache": services.pipeline.cache.stats(),
        },
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    return payload


@router.get("/metrics")
def metrics(request: Request) -> dict[str, Any]:
    services = get_services(request.app)
    limiter = getattr(request.app.state, "limiter", None)
    return {
        "qa": services.db.metrics(),
        "cache": services.db.cache_stats(),
        "feedback": services.db.feedback_stats(),
        "limits": limiter.stats() if limiter is not None else {},
        "index": {
            "documents": len(services.semantic.vector),
            "dim": int(services.semantic.vector.matrix.shape[1])
            if services.semantic.vector.matrix is not None
            else 0,
        },
        "recent": services.db.recent_traces(10),
    }


@router.get("/metrics/recent")
def recent(request: Request, limit: int = 20) -> list[dict[str, Any]]:
    return get_services(request.app).db.recent_traces(limit)


@router.get("/traces/{trace_id}")
def trace_detail(trace_id: str, request: Request) -> dict[str, Any]:
    from fastapi import HTTPException

    payload = get_services(request.app).db.get_trace(trace_id)
    if not payload:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return payload
