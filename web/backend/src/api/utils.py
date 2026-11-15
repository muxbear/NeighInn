from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.responses import ERR_PARAM, ApiError

MAX_PAGE_SIZE = 50


async def paginate(db: AsyncSession, stmt: Select, page: int, page_size: int):
    """服务端分页（SRS 8.3：默认 20、最大 50）。返回 (rows, total)。"""
    page = max(page, 1)
    if page_size < 1:
        page_size = 20
    if page_size > MAX_PAGE_SIZE:
        raise ApiError(ERR_PARAM, f"pageSize 最大 {MAX_PAGE_SIZE}", 400)
    total = int((await db.scalar(select(func.count()).select_from(stmt.subquery()))) or 0)
    rows = list((await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all())
    return rows, total


def camelize(value: Any) -> Any:
    if isinstance(value, dict):
        return {camelize_key(key): camelize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [camelize(item) for item in value]
    return value


def camelize_key(key: str) -> str:
    return re.sub(r"_([a-z])", lambda match: match.group(1).upper(), key)


def model_dict(row: Any) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}
