from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import client_ip
from src.core.responses import current_trace_id
from src.db.models import AdminUser, AuditLog


async def write_audit(
    db: AsyncSession,
    request: Request | None = None,
    *,
    actor: AdminUser | None = None,
    actor_name: str | None = None,
    action: str,
    resource_type: str = "",
    resource_id: str | int = "",
    before: Any = None,
    after: Any = None,
    result: str = "SUCCESS",
) -> AuditLog:
    """操作审计（W01-03）。关键操作必须调用：审核、配置变更、数据导出、
    权限变更、资金操作、敏感字段查看。只追加不可改删；资金/权限类与业务同事务提交。"""
    log = AuditLog(
        actor_id=actor.id if actor else None,
        actor_name=actor_name or (actor.real_name if actor else "系统"),
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        before_snapshot=before,
        after_snapshot=after,
        ip=client_ip(request) if request else "",
        user_agent=(request.headers.get("user-agent", "") if request else "")[:255],
        trace_id=current_trace_id(),
        result=result,
    )
    db.add(log)
    await db.flush()
    return log


async def write_outbox(
    db: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str | int,
    payload: dict,
) -> None:
    """事务性发件箱（后台详设 5.8.2）：业务事务内写入，Relay 异步投递。
    跨端一致性靠事件 + 缓存失效，不做双写。"""
    import uuid

    from src.db.models import OutboxEvent

    db.add(OutboxEvent(
        event_id=uuid.uuid4().hex,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        payload=payload,
    ))
    await db.flush()
