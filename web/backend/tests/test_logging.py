from __future__ import annotations

import json
import logging

from src.core.logging import JsonFormatter, RedactionFilter, mask_dsn, redact


def test_redact_sensitive_values():
    text = (
        "Authorization: Bearer abc.def.ghi token=secret123 "
        "DATABASE_URL=postgresql+psycopg://admin:secret@10.0.0.1:5432/db "
        "phone=13812345678 id=330106199001011234"
    )
    cleaned = redact(text)
    assert "abc.def.ghi" not in cleaned
    assert "secret123" not in cleaned
    assert "admin:secret@" not in cleaned
    assert "13812345678" not in cleaned
    assert "330106199001011234" not in cleaned
    assert "138****5678" in cleaned


def test_mask_dsn_hides_password():
    masked = mask_dsn("postgresql+psycopg://admin:secret@10.0.0.1:5432/neighinn_dev")
    assert "secret" not in masked
    assert "10.0.0.1:5432/neighinn_dev" in masked


def test_redaction_filter_masks_formatted_message():
    record = logging.LogRecord(
        name="src.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="token=%s", args=("abc123",), exc_info=None,
    )
    RedactionFilter().filter(record)
    assert "abc123" not in record.getMessage()
    assert "token=***" in record.getMessage()


def test_json_formatter_includes_context_and_extras():
    record = logging.LogRecord(
        name="src.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="http_request", args=(), exc_info=None,
    )
    record.trace_id = "trace-123"
    record.env = "test"
    record.service = "neighinn-backend"
    record.event = "http_request"
    record.method = "GET"
    record.path = "/api/v1/items"

    payload = json.loads(JsonFormatter().format(record))
    assert payload["level"] == "INFO"
    assert payload["traceId"] == "trace-123"
    assert payload["event"] == "http_request"
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/v1/items"


def test_sql_echo_disabled_by_default():
    from src.db.base import engine

    assert not engine.echo
    assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING
