from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_

from src.db.models import Broadcast
from src.db.models.common import ensure_utc, utcnow
from src.domain import enums as E

DEFAULT_EFFECTIVE_HOURS = 24

TYPE_LABELS = {
    "URGENT_HELP": "紧急求助",
    "FREE_NEW": "免费上新",
    "REWARD": "悬赏服务",
    "NEW_ITEM": "新上架",
}

_SCHEDULED_MODES = {"SCHEDULED", "RANGE", "CUSTOM", "TIMED", "定时", "定时生效", "指定时间段"}


def epoch_ms_to_utc(value: float | str | None) -> datetime | None:
    """把前端毫秒时间戳/ISO 时间转换为 naive UTC；兼容秒级时间戳与空值。"""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(UTC).replace(tzinfo=None)
            return parsed
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if abs(number) < 10_000_000_000:
        number *= 1000
    return datetime.fromtimestamp(number / 1000, tz=UTC).replace(tzinfo=None)


def to_epoch_ms(value: datetime | None) -> int:
    """数据库时间（可能是 aware 或 naive UTC）→ Unix 毫秒。"""
    if value is None:
        return 0
    normalized = ensure_utc(value)
    return int(normalized.replace(tzinfo=UTC).timestamp() * 1000)


def resolve_window(*, effective_mode: str | None = None,
                   start_at: float | str | None = None,
                   end_at: float | str | None = None,
                   scheduled_at: float | str | None = None,
                   expires_at: float | str | None = None,
                   duration_hours: int | None = None,
                   now: datetime | None = None) -> tuple[datetime, datetime, str]:
    """解析喇叭生效时间窗，返回 (开始, 结束, 存储状态)。

    - 即时生效：开始时间为当前时间；结束时间未填时默认 24 小时；
    - 定时生效：开始时间未填时默认 1 小时后；结束时间未填时默认开始后 24 小时；
    - 兼容仅传 startAt/endAt 的调用方（无 effectiveMode 时按时间自动判定）。
    """
    current = now or utcnow()
    mode = str(effective_mode or "").strip().upper()
    requested_start = epoch_ms_to_utc(start_at) or epoch_ms_to_utc(scheduled_at)
    requested_end = epoch_ms_to_utc(end_at) or epoch_ms_to_utc(expires_at)

    if mode == "IMMEDIATE":
        start = current
    elif mode in _SCHEDULED_MODES:
        start = requested_start or (current + timedelta(hours=1))
    else:
        start = requested_start or current

    if duration_hours and duration_hours > 0:
        end = start + timedelta(hours=duration_hours)
    else:
        end = requested_end or (start + timedelta(hours=DEFAULT_EFFECTIVE_HOURS))

    if end <= start:
        raise ValueError("结束时间必须晚于开始时间")

    status = E.ContentStatus.PUBLISHED if start <= current else E.ContentStatus.SCHEDULED
    return start, end, status


def visibility_filters(now: datetime | None = None) -> list:
    """移动端可见条件：已发布（含定时已到点）、已到开始时间、尚未过期。"""
    current = now or utcnow()
    return [
        or_(
            Broadcast.status == E.ContentStatus.PUBLISHED,
            and_(Broadcast.status == E.ContentStatus.SCHEDULED,
                 Broadcast.scheduled_at.is_not(None),
                 Broadcast.scheduled_at <= current),
        ),
        or_(Broadcast.scheduled_at.is_(None), Broadcast.scheduled_at <= current),
        or_(Broadcast.expires_at.is_(None), Broadcast.expires_at > current),
    ]


def is_visible(broadcast: Broadcast, now: datetime | None = None) -> bool:
    current = now or utcnow()
    scheduled_at = ensure_utc(broadcast.scheduled_at)
    expires_at = ensure_utc(broadcast.expires_at)
    if broadcast.status == E.ContentStatus.SCHEDULED:
        if not scheduled_at or scheduled_at > current:
            return False
    elif broadcast.status != E.ContentStatus.PUBLISHED:
        return False
    if scheduled_at and scheduled_at > current:
        return False
    return not (expires_at and expires_at <= current)
