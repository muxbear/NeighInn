from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from src.core.responses import ApiError


def model_dict(model: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    result: dict[str, Any] = {}
    for column in inspect(model).mapper.column_attrs:
        key = column.key
        if key in exclude or key in {"password_hash", "two_factor_secret"}:
            continue
        value = getattr(model, key)
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        result[key] = value
    return result


def camelize(data: Any) -> Any:
    """Small helper for API-facing dicts; keeps model keys readable for the SPA."""
    if isinstance(data, list):
        return [camelize(item) for item in data]
    if isinstance(data, dict):
        return {_camel(key): camelize(value) for key, value in data.items()}
    return data


def _camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


async def paginate(db: AsyncSession, stmt: Select, page: int, page_size: int) -> tuple[list[Any], int]:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int((await db.scalar(count_stmt)) or 0)
    rows = await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    return list(rows.scalars().all()), total


async def get_or_404(db: AsyncSession, model: Any, object_id: int) -> Any:
    obj = await db.get(model, object_id)
    if not obj:
        raise ApiError(40401, "资源不存在", 404)
    return obj


def query_param(request: Request, name: str, default: str | None = None) -> str | None:
    value = request.query_params.get(name)
    return value if value not in (None, "") else default
