"""应用工厂与启动生命周期。"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import STATIC_DIR, settings
from app.services.tempfiles import cleanup_stale_files
from app.services.transcriber import Transcriber

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

TRANSCRIBE_PATH = "/api/transcribe"


class BodySizeLimitMiddleware:
    """在读取请求体之前按 Content-Length 拦截超限上传，避免大文件进入内存。"""

    def __init__(self, app, max_body_size: int):
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != TRANSCRIBE_PATH:
            await self.app(scope, receive, send)
            return

        content_length = dict(scope.get("headers") or []).get(b"content-length")
        if content_length is not None:
            try:
                too_large = int(content_length) > self.max_body_size
            except ValueError:
                too_large = False
            if too_large:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": "File too large. Maximum size is 10MB."},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(
        title="本地语音识别 Web 应用",
        description="faster-whisper + FastAPI 的离线中英文语音转文字服务",
        version="0.1.0",
    )

    transcriber = Transcriber()
    app.state.transcriber = transcriber
    app.state.model_error = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        removed = cleanup_stale_files(settings.temp_max_age_seconds)
        if removed:
            logger.info("startup: 清理残留临时音频 %s 个", removed)
        if settings.preload_model:
            try:
                app.state.transcriber.load()
            except Exception as exc:  # 加载失败不阻断启动，/health 反映状态
                app.state.model_error = str(exc)
                logger.critical("模型加载失败: %s", exc)
        yield
        logger.info("shutdown: 服务停止")

    app.router.lifespan_context = lifespan

    app.add_middleware(BodySizeLimitMiddleware, max_body_size=settings.max_body_size)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("未捕获异常 path=%s: %s", request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )

    app.include_router(router)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()
