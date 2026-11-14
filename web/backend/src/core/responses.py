from __future__ import annotations

from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")


def current_trace_id() -> str:
    return trace_id_ctx.get() or uuid4().hex[:16]


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data, "traceId": current_trace_id()}


def paginated(items: list[Any], page: int, page_size: int, total: int) -> dict[str, Any]:
    return ok({"items": items, "page": page, "pageSize": page_size, "total": total})


class ApiError(Exception):
    def __init__(self, code: int, message: str, http_status: int = 400, details: Any = None) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details
        super().__init__(message)


async def api_error_handler(request: Request, exc: ApiError):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=exc.http_status,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": exc.details,
            "traceId": current_trace_id(),
        },
    )


async def http_error_handler(request: Request, exc: HTTPException):
    from fastapi.responses import JSONResponse

    code = 40001
    if exc.status_code == 401:
        code = 40101
    elif exc.status_code == 403:
        code = 40301
    elif exc.status_code == 404:
        code = 40401
    elif exc.status_code == 429:
        code = 42901
    elif exc.status_code >= 500:
        code = 50000
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": str(exc.detail), "data": None, "traceId": current_trace_id()},
    )
