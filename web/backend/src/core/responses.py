from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")


def _level_for_status(status: int) -> int:
    """4xx 中仅认证/权限/限流升为 WARNING，其余按 INFO 记录，避免正常业务噪声。"""
    if status >= 500:
        return logging.ERROR
    if status in {401, 403, 429}:
        return logging.WARNING
    return logging.INFO


def current_trace_id() -> str:
    return trace_id_ctx.get() or uuid.uuid4().hex[:16]


class ApiError(Exception):
    """统一业务异常。错误码对齐 SRS 8.3 / 后台详设 7.4.1。"""

    def __init__(self, code: int, message: str, http_status: int = 400, data: Any = None):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data
        super().__init__(message)


# 标准错误码（SRS 8.3、后台详设 7.4.1）
ERR_PARAM = 40001          # 参数校验失败
ERR_UNAUTHORIZED = 40101   # 未登录/Token 失效
ERR_BAD_CREDENTIALS = 40102
ERR_2FA_REQUIRED = 40103
ERR_2FA_INVALID = 40104
ERR_FORBIDDEN = 40301      # 无权限
ERR_DATA_SCOPE = 40302     # 数据范围越界
ERR_FIELD_SCOPE = 40303    # 字段权限不足
ERR_NOT_VERIFIED = 40304   # 未完成认证
ERR_RELATION_BLOCKED = 40305  # 关系已阻断（拉黑/认证失效）
ERR_MUST_CHANGE_PASSWORD = 40306  # 首次登录/重置后需先修改初始密码
ERR_NOT_FOUND = 40401
ERR_CONFLICT = 40901       # 占用/处理中（如物品已被预约、幂等处理中）
ERR_IDEMPOTENT_CONFLICT = 40902  # 同一幂等键不同请求体
ERR_VERSION_CONFLICT = 40903     # 乐观锁冲突
ERR_INVALID_TRANSITION = 40904   # 非法状态迁移
ERR_FILE_TOO_LARGE = 41301
ERR_BIZ_RULE = 42201       # 业务规则不满足（含 AI 质检未通过）
ERR_AI_REJECTED = 42202
ERR_DUAL_REVIEW = 42203    # 资金需双人复核/复核人相同
ERR_RECON_DIFF = 42204     # 对账差异未处理禁止关闭
ERR_RATE_LIMIT = 42901
ERR_INTERNAL = 50000
ERR_NOT_IMPLEMENTED = 50001  # 骨架占位：接口已声明、逻辑未实现
ERR_DEPENDENCY = 50301     # 依赖不可用


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data, "traceId": current_trace_id()}


def paginated(items: list, page: int, page_size: int, total: int) -> dict:
    return ok({
        "items": items,
        "page": page,
        "pageSize": page_size,
        "total": total,
        "hasMore": page * page_size < total,
    })


def not_implemented(what: str) -> ApiError:
    return ApiError(ERR_NOT_IMPLEMENTED, f"{what} 尚未实现（Phase 0 契约骨架）", 501)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    logger.log(
        _level_for_status(exc.http_status),
        "api_error code=%s status=%s path=%s message=%s",
        exc.code, exc.http_status, request.url.path, exc.message,
        extra={"event": "api_error", "code": exc.code, "status": exc.http_status,
               "path": request.url.path},
    )
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "data": exc.data,
                 "traceId": current_trace_id()},
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code_map = {404: ERR_NOT_FOUND, 405: ERR_PARAM, 401: ERR_UNAUTHORIZED, 403: ERR_FORBIDDEN}
    logger.log(
        _level_for_status(exc.status_code),
        "http_error status=%s path=%s message=%s",
        exc.status_code, request.url.path, exc.detail,
        extra={"event": "http_error", "status": exc.status_code, "path": request.url.path},
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code_map.get(exc.status_code, ERR_INTERNAL),
                 "message": str(exc.detail), "data": None, "traceId": current_trace_id()},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error path=%s", request.url.path,
                     extra={"event": "unhandled_error", "path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={"code": ERR_INTERNAL, "message": "系统错误", "data": None,
                 "traceId": current_trace_id()},
    )
