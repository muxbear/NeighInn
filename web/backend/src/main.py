from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.config import settings
from src.core.logging import configure_logging, mask_dsn
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

configure_logging()
logger = logging.getLogger(__name__)

_ACCESS_SKIP_PATHS = settings.access_log_skip_path_set


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 1)


def _log_access(request: Request, status: int, duration_ms: float,
                reason: str | None = None) -> None:
    """应用级访问日志：uvicorn.access 已关闭，由这里统一输出。"""
    if not settings.access_log_enabled or request.url.path in _ACCESS_SKIP_PATHS:
        return
    slow = duration_ms >= settings.slow_request_ms
    if status >= 500:
        level = logging.ERROR
    elif status >= 400 or slow:
        level = logging.WARNING
    else:
        level = logging.INFO
    event = "http_slow" if slow and status < 400 else "http_request"
    extra = {
        "event": event,
        "method": request.method,
        "path": request.url.path,
        "status": status,
        "durationMs": duration_ms,
        "clientIp": request.client.host if request.client else "-",
    }
    if reason:
        extra["reason"] = reason
    logger.log(level, event, extra=extra)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from src.services.auth_service import sms_code_store

    started_at = time.perf_counter()
    logger.info(
        "startup config env=%s sql_echo=%s db=%s redis=%s minio=%s scheduler=%s",
        settings.app_env,
        settings.sql_echo,
        mask_dsn(settings.database_url),
        "configured" if settings.redis_url else "memory",
        settings.minio_endpoint,
        settings.enable_scheduler,
        extra={"event": "startup", "step": "config"},
    )

    step_at = time.perf_counter()
    await init_db()
    logger.info("startup step=db durationMs=%.1f", _elapsed_ms(step_at),
                extra={"event": "startup", "step": "db", "durationMs": _elapsed_ms(step_at)})

    step_at = time.perf_counter()
    await session_store.init()
    session_backend = getattr(session_store, "backend_name", "unknown")
    logger.info("startup step=session_store backend=%s durationMs=%.1f",
                session_backend, _elapsed_ms(step_at),
                extra={"event": "startup", "step": "session_store",
                       "backend": session_backend, "durationMs": _elapsed_ms(step_at)})

    step_at = time.perf_counter()
    await sms_code_store.init()
    sms_backend = getattr(sms_code_store, "backend_name", "unknown")
    logger.info("startup step=sms_store backend=%s durationMs=%.1f",
                sms_backend, _elapsed_ms(step_at),
                extra={"event": "startup", "step": "sms_store",
                       "backend": sms_backend, "durationMs": _elapsed_ms(step_at)})

    if settings.app_env == "dev":
        # 幂等种子：区划/社区/类目/字典/权限/角色/超管/参数/热词（生产用 alembic data migration）
        step_at = time.perf_counter()
        async with SessionLocal() as session:
            seed_summary = await seed_if_empty(session)
        if seed_summary:
            logger.info("startup step=seed mode=created %s durationMs=%.1f",
                        seed_summary, _elapsed_ms(step_at),
                        extra={"event": "startup", "step": "seed", "mode": "created",
                               "durationMs": _elapsed_ms(step_at), **seed_summary})
        else:
            logger.info("startup step=seed mode=skipped durationMs=%.1f",
                        _elapsed_ms(step_at),
                        extra={"event": "startup", "step": "seed", "mode": "skipped",
                               "durationMs": _elapsed_ms(step_at)})

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

    logger.info("startup complete listen=%s:%s durationMs=%.1f",
                settings.app_host, settings.app_port, _elapsed_ms(started_at),
                extra={"event": "startup", "step": "complete",
                       "listen": f"{settings.app_host}:{settings.app_port}",
                       "durationMs": _elapsed_ms(started_at)})
    yield

    shutdown_at = time.perf_counter()
    logger.info("shutdown begin", extra={"event": "shutdown"})
    stop.set()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await sms_code_store.close()
    await session_store.close()
    logger.info("shutdown complete durationMs=%.1f", _elapsed_ms(shutdown_at),
                extra={"event": "shutdown", "durationMs": _elapsed_ms(shutdown_at)})


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="邻里小栈统一服务端：C 端 /api/v1 与管理端 /api/v1/admin 共享领域模型",
    lifespan=lifespan,
)

@app.middleware("http")
async def request_context(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex[:16]
    trace_id_ctx.set(trace_id)
    started_at = time.perf_counter()
    if (
        settings.auth_enforce_csrf
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.url.path.startswith("/api/v1/admin")
        and not request.url.path.endswith("/auth/login")
    ):
        cookie = request.cookies.get("ni_csrf")
        header = request.headers.get("x-csrf-token")
        if not cookie or not header or cookie != header:
            _log_access(request, 403, _elapsed_ms(started_at), reason="csrf")
            return JSONResponse(
                status_code=403,
                content={"code": 40301, "message": "CSRF 校验失败", "data": None,
                         "traceId": trace_id},
            )
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 - 全局兜底必须捕获全部异常才能返回统一错误体
        # 在中间件内部兜底，确保 500 响应也会经过外层 CORSMiddleware（见下方顺序说明），
        # 否则浏览器会因缺少 CORS 头把 500 报成「网络连接失败」而非真实错误。
        _log_access(request, 500, _elapsed_ms(started_at))
        response = await unhandled_error_handler(request, exc)
    else:
        _log_access(request, response.status_code, _elapsed_ms(started_at))
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# 开发环境允许私网 IP 的移动端 H5 来源（真机/局域网调试）；生产环境仅使用显式白名单。
# 注意：必须最后添加，使 CORSMiddleware 位于 request_context 外层；Starlette 后添加的
# 中间件更靠外，这样即使 request_context 生成 500 响应也能补上 CORS 头。
_origin_regex = settings.cors_origin_regex if settings.app_env == "dev" else ""

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    from src.core.responses import current_trace_id

    # 不记录原始 input，避免密码/手机号等被 Pydantic 错误上下文带进日志。
    safe_errors = [
        {"loc": list(item.get("loc", ())), "type": item.get("type"),
         "msg": item.get("msg")}
        for item in exc.errors()
    ]
    logger.warning("validation_error path=%s errors=%s", request.url.path, safe_errors,
                   extra={"event": "validation_error", "path": request.url.path,
                          "errors": safe_errors})
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
