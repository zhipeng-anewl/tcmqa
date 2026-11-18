# -*- coding: utf-8 -*-
"""FastAPI 应用装配。

启动顺序：配置 → 日志 → 单例服务（Neo4j / 链接索引 / 检索索引 / SQLite）→ 路由。
关停时按相反顺序释放，避免驱动泄漏。
"""

from __future__ import annotations

import logging
import mimetypes
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# Windows 注册表通常没登记 .webp，不补这一行 StaticFiles 会返回 application/octet-stream，
# 部分浏览器下 <img> 就渲染不出来。
mimetypes.add_type("image/webp", ".webp")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from tcmqa import __version__
from tcmqa.api import chat, graph, health, media, vision
from tcmqa.api.deps import build_services
from tcmqa.api.ratelimit import RateLimiter, client_ip
from tcmqa.logging import reset_request_id, set_request_id, setup_logging
from tcmqa.settings import BASE_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

# Vue3 + Vite 构建产物（cd frontend && npm run build）
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        started = time.perf_counter()
        logger.info("正在初始化服务…")
        app.state.services = build_services(settings)
        logger.info("服务就绪，耗时 %.1fs", time.perf_counter() - started)
        try:
            yield
        finally:
            logger.info("正在释放资源…")
            app.state.services.close()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "基于 Neo4j 中医药知识图谱的 GraphRAG 问答系统。"
            "支持意图路由、Text2Cypher 自修复、向量+BM25 混合检索、"
            "证据引用、语义缓存与全链路追踪。"
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------- 中间件：request_id + 访问日志 ---------------- #
    @app.middleware("http")
    async def access_log(request: Request, call_next):
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
        token = set_request_id(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            logger.exception("未捕获异常 path=%s", request.url.path)
            raise
        finally:
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            reset_request_id(token)

        response.headers["X-Request-Id"] = rid
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )
        return response

    # ---------------- 限流：公网部署时的成本与滥用防线 ---------------- #
    # 默认关闭（两个阈值都是 0），本地开发不受影响；docker-compose.prod.yml 里打开。
    limiter = RateLimiter(
        per_minute=settings.rate_limit_per_minute,
        daily_limit=settings.daily_chat_limit,
    )
    app.state.limiter = limiter

    if limiter.enabled:
        costly = ("/api/chat", "/api/vision", "/api/graph/cypher")

        @app.middleware("http")
        async def rate_limit(request: Request, call_next):
            if request.url.path.startswith(costly):
                ip = client_ip(
                    dict(request.headers),
                    request.client.host if request.client else "",
                    settings.trust_proxy_headers,
                )
                ok, retry_after, reason = limiter.allow(ip)
                if not ok:
                    message = (
                        "今日问答额度已用完，请明天再来"
                        if reason == "daily"
                        else "请求太频繁，请稍后再试"
                    )
                    return JSONResponse(
                        status_code=429,
                        content={"detail": message, "reason": reason, "retry_after": retry_after},
                        headers={"Retry-After": str(retry_after)},
                    )
            return await call_next(request)

    # ---------------- 统一错误格式 ---------------- #
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # 详细堆栈只进日志：响应体里带上 str(exc) 可能泄露数据库地址、
        # 文件绝对路径等内部信息，公网部署时是不必要的攻击面。
        logger.exception("服务器内部错误 path=%s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务器内部错误"},
        )

    # ---------------- 路由 ---------------- #
    app.include_router(chat.router, prefix="/api")
    app.include_router(graph.router, prefix="/api")
    app.include_router(health.router, prefix="/api")
    app.include_router(media.router, prefix="/api")
    app.include_router(vision.router, prefix="/api")

    # ---------------- 图片静态目录 ----------------
    # 封面是我们预生成的（data/images/herb），分子结构图直接用原始目录（体积小，不必转换）。
    # 目录不存在时跳过挂载，保证没有图也能起服务。
    covers = Path(settings.media_dir) / "herb"
    if covers.is_dir():
        app.mount("/media/covers", StaticFiles(directory=str(covers)), name="covers")

    gallery = Path(settings.media_dir) / "herb_gallery"
    if gallery.is_dir():
        app.mount("/media/gallery", StaticFiles(directory=str(gallery)), name="gallery")

    mol_root = Path(settings.mol_image_root)
    if mol_root.is_dir():
        app.mount("/media/mol", StaticFiles(directory=str(mol_root)), name="molecules")

    # ---------------- 静态前端（Vue3 构建产物） ---------------- #
    # 挂在根路径，html=True 会处理 index.html；/api、/media 等路由注册在前，不受影响。
    if (FRONTEND_DIST / "index.html").is_file():
        app.mount(
            "/",
            StaticFiles(directory=str(FRONTEND_DIST), html=True),
            name="frontend",
        )
    else:

        @app.get("/", include_in_schema=False)
        def index_missing() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "前端未构建：请在 frontend/ 下执行 npm install && npm run build",
                },
            )

    return app


app = create_app()
