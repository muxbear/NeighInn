from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.responses import (
    ERR_CONFLICT,
    ERR_IDEMPOTENT_CONFLICT,
    ApiError,
    current_trace_id,
)
from src.db.models import IdempotencyKey


async def guard_idempotency(
    db: AsyncSession,
    request: Request,
    body: dict | None = None,
    ttl_hours: int = 24,
) -> IdempotencyKey | None:
    """写操作幂等守卫（SRS 8.3、后台详设 5.8.3）。

    - 同一 key 不同请求体 → 40902；
    - 同一 key 处理中 → 40901；
    - 同一 key 已完成 → 调用方应直接返回缓存的 response_json（见 complete_idempotency）。

    用法（在每个写 Handler 开头）：
        record = await guard_idempotency(db, request, body)
        if record and record.status == "COMPLETED":
            return ok(record.response_json)
        ...业务逻辑...
        await complete_idempotency(db, record, response_data)
    """
    key = request.headers.get("x-idempotency-key")
    if not key:
        return None
    key = key.strip()[:64]
    request_hash = hashlib.sha256(
        json.dumps(body or {}, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()

    existing = await db.get(IdempotencyKey, key)
    if existing:
        if existing.request_hash != request_hash:
            raise ApiError(ERR_IDEMPOTENT_CONFLICT, "幂等键与请求体不匹配", 409)
        if existing.status == "PROCESSING":
            raise ApiError(ERR_CONFLICT, "相同请求正在处理中，请稍后查询结果", 409)
        return existing  # COMPLETED → 调用方短路返回缓存响应

    record = IdempotencyKey(
        key=key,
        request_hash=request_hash,
        status="PROCESSING",
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
    db.add(record)
    await db.flush()
    return record


async def complete_idempotency(
    db: AsyncSession, record: IdempotencyKey | None, response_data: dict | None
) -> None:
    if record is None:
        return
    record.status = "COMPLETED"
    record.response_json = {"data": response_data, "traceId": current_trace_id()}
    await db.flush()


async def cleanup_expired_keys(db: AsyncSession) -> int:
    rows = await db.execute(
        select(IdempotencyKey).where(IdempotencyKey.expires_at < datetime.now(UTC))
    )
    count = 0
    for row in rows.scalars().all():
        await db.delete(row)
        count += 1
    return count
