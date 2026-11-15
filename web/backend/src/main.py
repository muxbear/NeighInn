from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.config import settings
from src.core.responses import (
    ApiError,
    api_error_handler,
    http_error_handler,
    trace_id_ctx,
    unhandled_error_handler,
)
from src.core.sessions import session_store
from src.db.base import SessionLocal, init_db
from src.db.seed import seed_if_empty

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await session_store.init()
    if settings.app_env == "dev":
        # 幂等种子：区划/社区/类目/字典/权限/角色/超管/参数/热词（生产用 alembic data migration）
        async with SessionLocal() as session:
            await seed_if_empty(session)

    stop = asyncio.Event()
    tasks: list[asyncio.Task] = []
    if settings.enable_scheduler:
        from src.workers.outbox_relay import relay_loop
        from src.workers.timeout_tasks import timeout_loop

        tasks = [
            asyncio.create_task(relay_loop(settings.outbox_interval_seconds, stop)),
            asyncio.create_task(timeout_loop(settings.timeout_interval_seconds, stop)),
        ]
        logger.info("调度已启动：outbox=%ss timeout=%ss",
                    settings.outbox_interval_seconds, settings.timeout_interval_seconds)

    yield

    stop.set()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await session_store.close()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="邻里小栈统一服务端：C 端 /api/v1 与管理端 /api/v1/admin 共享领域模型",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex[:16]
    trace_id_ctx.set(trace_id)
    if (
        settings.auth_enforce_csrf
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.url.path.startswith("/api/v1/admin")
        and not request.url.path.endswith("/auth/login")
    ):
        cookie = request.cookies.get("ni_csrf")
        header = request.headers.get("x-csrf-token")
        if not cookie or not header or cookie != header:
            return JSONResponse(
                status_code=403,
                content={"code": 40301, "message": "CSRF 校验失败", "data": None,
                         "traceId": trace_id},
            )
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    from src.core.responses import current_trace_id

    return JSONResponse(
        status_code=400,
        content={"code": 40001, "message": "参数校验失败", "data": exc.errors(),
                 "traceId": current_trace_id()},
    )


from src.api.admin import admin_router
from src.api.c_end import c_router

# C 端（移动端）：/api/v1，JWT Bearer
app.include_router(c_router, prefix="/api/v1")
# 管理端（Web 后台）：/api/v1/admin，Cookie 会话 + CSRF + 2FA
app.include_router(admin_router, prefix="/api/v1/admin")


@app.get("/health/live", tags=["health"])
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def health_ready():
    return {"status": "ready", "env": settings.app_env}
