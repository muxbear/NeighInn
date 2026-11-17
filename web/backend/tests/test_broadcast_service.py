from __future__ import annotations

from datetime import UTC, timedelta

from src.db.models import Broadcast
from src.db.models.common import utcnow
from src.services.broadcast_service import is_visible, to_epoch_ms


def test_visibility_accepts_postgres_aware_datetimes():
    """PostgreSQL 返回带时区时间，不能与 naive UTC 直接比较（线上 500 回归）。"""
    now = utcnow()
    broadcast = Broadcast(
        community_id=1,
        title="时区兼容",
        status="PUBLISHED",
        scheduled_at=(now - timedelta(minutes=1)).replace(tzinfo=UTC),
        expires_at=(now + timedelta(hours=1)).replace(tzinfo=UTC),
    )
    assert is_visible(broadcast, now)


def test_visibility_rejects_future_or_expired_aware_datetimes():
    now = utcnow()
    future = Broadcast(
        community_id=1,
        title="未来定时",
        status="SCHEDULED",
        scheduled_at=(now + timedelta(hours=1)).replace(tzinfo=UTC),
        expires_at=(now + timedelta(hours=2)).replace(tzinfo=UTC),
    )
    expired = Broadcast(
        community_id=1,
        title="已过期",
        status="PUBLISHED",
        scheduled_at=(now - timedelta(hours=2)).replace(tzinfo=UTC),
        expires_at=(now - timedelta(hours=1)).replace(tzinfo=UTC),
    )
    assert not is_visible(future, now)
    assert not is_visible(expired, now)


def test_to_epoch_ms_normalizes_aware_and_naive_utc():
    now = utcnow()
    assert to_epoch_ms(now) == to_epoch_ms(now.replace(tzinfo=UTC))
