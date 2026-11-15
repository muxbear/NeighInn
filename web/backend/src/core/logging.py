"""统一日志配置。

设计目标：
- 开发环境输出可读的单行 console 日志；生产环境输出单行 JSON，便于采集；
- root/uvicorn/SQLAlchemy 共用一条 handler 链，避免同一日志重复输出；
- 所有日志自动注入 traceId，并对密码、Token、手机号、身份证号脱敏；
- SQL 日志由 SQL_ECHO 独立控制，不再和 DEBUG 耦合；
- 默认不写本地文件（12-factor：stdout），需要时通过 LOG_TO_FILE 开启轮转文件。
"""

from __future__ import annotations

import json
import logging
import logging.config
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.core.config import settings
from src.core.responses import trace_id_ctx

# LogRecord 自带字段 + 本模块注入的上下文字段，JSON 序列化时跳过。
_RESERVED_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "trace_id",
    "env",
    "service",
    "event",
    "exception",
    "exc_text",
    "color_message",
}

# console 模式只展示这些结构化字段，避免把内部调试字段全部铺开。
_CONSOLE_EXTRA_KEYS = (
    "event",
    "method",
    "path",
    "status",
    "durationMs",
    "clientIp",
    "userId",
    "code",
    "step",
    "backend",
    "mode",
    "reason",
    "listen",
)

_DSN_RE = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")
_AUTH_RE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie|x-csrf-token|x-refresh-token)\b"
    r"(\s*[:=]\s*)(?:Bearer\s+)?(\S+)"
)
_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|secret|secret_key|access_key|token|api_key)\b"
    r"(\s*[:=]\s*)(\S+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?!\d)")


def redact(value: str) -> str:
    """对日志文本做最小必要脱敏；不做全量加密，避免破坏可读性。"""
    value = _BEARER_RE.sub("Bearer ***", value)
    value = _AUTH_RE.sub(r"\1\2***", value)
    value = _SECRET_RE.sub(r"\1\2***", value)
    value = _DSN_RE.sub(r"\1***\3", value)
    value = _PHONE_RE.sub(r"\1****\2", value)
    value = _ID_CARD_RE.sub(r"\1********\2", value)
    return value


def mask_dsn(value: str | None) -> str:
    """仅保留 DSN 的主机/库名，密码替换为 ***。"""
    if not value:
        return "-"
    return _DSN_RE.sub(r"\1***\3", value)


class ContextFilter(logging.Filter):
    """把请求上下文注入每条日志。"""

    def __init__(self, service: str, env: str) -> None:
        super().__init__()
        self.service = service
        self.env = env

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_ctx.get() or "-"
        record.env = self.env
        record.service = self.service
        return True


class RedactionFilter(logging.Filter):
    """在进入 handler 前对消息做脱敏，兜底防止敏感信息落盘。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - 日志格式化失败不应影响业务
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


class _RedactingFormatter(logging.Formatter):
    def formatException(self, ei) -> str:
        return redact(super().formatException(ei))

    def formatStack(self, stack_info: str) -> str:
        return redact(super().formatStack(stack_info))


class ConsoleFormatter(_RedactingFormatter):
    """开发环境：时间 + 级别 + logger + traceId + 消息 + 常用结构化字段。"""

    def __init__(self, fmt: str | None = None, datefmt: str | None = None) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras: list[str] = []
        for key in _CONSOLE_EXTRA_KEYS:
            value = getattr(record, key, None)
            if value is None:
                continue
            if key == "event" and value == record.getMessage():
                continue
            # 消息里已带 key=value 时不再重复展示（如 startup step=db durationMs=...）。
            if f"{key}=" in base:
                continue
            extras.append(f"{key}={redact(str(value))}")
        return f"{base} {' '.join(extras)}" if extras else base


class JsonFormatter(_RedactingFormatter):
    """生产环境：单行 JSON，固定字段 + 业务 extra 字段 + 异常堆栈。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "traceId": getattr(record, "trace_id", "-"),
            "env": getattr(record, "env", settings.app_env),
            "service": getattr(record, "service", settings.app_name),
        }
        event = getattr(record, "event", None)
        if event:
            payload["event"] = event

        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            if isinstance(value, str):
                payload[key] = redact(value)
            elif isinstance(value, (int, float, bool)) or value is None:
                payload[key] = value
            else:
                try:
                    json.dumps(value)
                except (TypeError, ValueError):
                    payload[key] = str(value)
                else:
                    payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def configure_logging(*, force: bool = False, log_to_file: bool | None = None) -> None:
    """初始化统一日志配置；可重复调用（默认只生效一次）。

    Args:
        force: 强制重新配置，测试或运行期切换日志级别时使用。
        log_to_file: 覆盖 LOG_TO_FILE；uvicorn reload 的父进程用 False，避免父子进程同时写文件。
    """
    global _configured
    if _configured and not force:
        return

    level = settings.log_level.upper()
    use_json = settings.log_format.lower() == "json"
    formatter_name = "json" if use_json else "console"
    use_file = settings.log_to_file if log_to_file is None else log_to_file

    handlers: list[str] = ["console"]
    handler_config: dict[str, dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": formatter_name,
            "filters": ["context", "redaction"],
        }
    }

    if use_file:
        try:
            log_dir = Path(settings.log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - 文件系统异常时优雅降级
            print(f"[logging] 无法创建日志目录 {settings.log_dir}: {exc}", file=sys.stderr)
        else:
            file_common = {
                "class": "logging.handlers.RotatingFileHandler",
                "maxBytes": settings.log_max_bytes,
                "backupCount": settings.log_backup_count,
                "encoding": "utf-8",
                "formatter": formatter_name,
                "filters": ["context", "redaction"],
            }
            handler_config["file"] = {
                **file_common,
                "filename": str(log_dir / "app.log"),
            }
            handler_config["error_file"] = {
                **file_common,
                "filename": str(log_dir / "error.log"),
                "level": "ERROR",
            }
            handlers.extend(["file", "error_file"])

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "context": {
                "()": "src.core.logging.ContextFilter",
                "service": settings.app_name,
                "env": settings.app_env,
            },
            "redaction": {"()": "src.core.logging.RedactionFilter"},
        },
        "formatters": {
            "console": {
                "()": "src.core.logging.ConsoleFormatter",
                "fmt": "%(asctime)s %(levelname)-7s %(name)s [%(trace_id)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {"()": "src.core.logging.JsonFormatter"},
        },
        "handlers": handler_config,
        "root": {"level": level, "handlers": handlers},
        "loggers": {
            # uvicorn 生命周期日志汇入 root；访问日志由应用中间件统一输出。
            "uvicorn": {"handlers": [], "level": level, "propagate": True},
            "uvicorn.error": {"handlers": [], "level": level, "propagate": True},
            "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": False},
            # SQL 日志独立开关；echo 固定 False，避免 SQLAlchemy 安装第二个 handler。
            "sqlalchemy.engine": {
                "handlers": [],
                "level": "INFO" if settings.sql_echo else "WARNING",
                "propagate": True,
            },
            "sqlalchemy.pool": {"handlers": [], "level": "WARNING", "propagate": True},
            "alembic": {"handlers": [], "level": "WARNING", "propagate": True},
            # 第三方库默认降噪，避免连接池/HTTP 客户端把业务日志淹没。
            "httpx": {"handlers": [], "level": "WARNING", "propagate": True},
            "httpcore": {"handlers": [], "level": "WARNING", "propagate": True},
            "urllib3": {"handlers": [], "level": "WARNING", "propagate": True},
            "minio": {"handlers": [], "level": "WARNING", "propagate": True},
            "redis": {"handlers": [], "level": "WARNING", "propagate": True},
            "asyncio": {"handlers": [], "level": "WARNING", "propagate": True},
            "watchfiles": {"handlers": [], "level": "WARNING", "propagate": True},
            "multipart": {"handlers": [], "level": "WARNING", "propagate": True},
        },
    }

    logging.config.dictConfig(config)
    _configured = True
