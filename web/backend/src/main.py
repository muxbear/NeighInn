from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api import (
    auth,
    communication,
    communities,
    dashboard,
    files,
    finance,
    governance,
    operations,
    residents,
    system,
)
from src.core.config import settings
from src.core.responses import ApiError, api_error_handler, current_trace_id, http_error_handler, trace_id_ctx
from src.core.sessions import session_store
from src.db.base import SessionLocal, init_db
from src.db.seed import repair_seed_data, seed_if_empty

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await session_store.init()
    async with SessionLocal() as session:
        await seed_if_empty(session)
        await repair_seed_data(session)
    yield
    await session_store.close()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="邻里小栈社区运营管理平台 API",
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
    trace_id = request.headers.get("x-trace-id") or __import__("uuid").uuid4().hex[:16]
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
                content={"code": 40301, "message": "CSRF 校验失败", "data": None, "traceId": trace_id},
            )
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={
            "code": 40001,
            "message": "参数校验失败",
            "data": exc.errors(),
            "traceId": current_trace_id(),
        },
    )


prefix = "/api/v1/admin"
for router in (
    auth.router,
    dashboard.router,
    communities.router,
    residents.router,
    operations.router,
    communication.router,
    governance.router,
    system.router,
    finance.router,
    files.router,
):
    app.include_router(router, prefix=prefix)


@app.get("/health/live", tags=["health"])
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def health_ready():
    return {"status": "ready", "env": settings.app_env}


@app.get("/", tags=["health"])
async def root():
    return {"name": settings.app_name, "docs": "/docs", "api": prefix}
