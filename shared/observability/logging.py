"""Structured JSON logging with a stable schema for the SOC SIEM.

Every line emitted by any service follows the schema documented in
``docs/observability.md``. Required keys on every record:

* ``ts`` — ISO-8601 timestamp (UTC).
* ``schema_version`` — log-schema version, bumped on breaking changes so
  Splunk / Elastic / Datadog parsers can pin.
* ``service`` — emitting service (``rt-ai-ids-api``, ``rt-ai-ids-inference``,
  …). Drives Splunk source typing.
* ``level`` — Python log level name.
* ``logger`` — Python logger name (file path, useful for grep but not for
  routing).
* ``event`` — short snake_case event name (e.g. ``predict_job_enqueued``).
  Equal to the log message when the call site doesn't pass ``extra={"event":...}``.
* ``message`` — human-readable message.
* ``correlation_id`` — request / job correlation id bound via
  :func:`bind_correlation_id`.
* ``trace_id`` / ``span_id`` — populated when an OTel span is active.

Anything else passed via ``extra={...}`` is included verbatim as long as it's
JSON-serialisable.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
    "taskName",
}


def _utc_isoformat(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds")


class _JsonFormatter(logging.Formatter):
    """Render log records as one JSON object per line under the SIEM schema."""

    def __init__(
        self,
        *,
        service: str,
        schema_version: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._schema_version = schema_version

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload: dict[str, Any] = {
            "ts": _utc_isoformat(record),
            "schema_version": self._schema_version,
            "service": self._service,
            "level": record.levelname,
            "logger": record.name,
            "event": message,
            "message": message,
        }
        cid = _correlation_id.get()
        if cid:
            payload["correlation_id"] = cid

        # Best-effort OTel correlation. Imported lazily so log-only deploys
        # don't pull in the SDK.
        try:  # pragma: no cover - exercised in tracing tests
            from .tracing import get_span_id, get_trace_id

            trace_id = get_trace_id()
            span_id = get_span_id()
            if trace_id:
                payload["trace_id"] = trace_id
            if span_id:
                payload["span_id"] = span_id
        except Exception:
            pass

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            # Allow callers to override ``event`` via extra={"event": "..."}.
            payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(
    level: str | None = None,
    *,
    service: str | None = None,
    schema_version: str | None = None,
) -> None:
    """Install the JSON formatter on the root logger.

    Idempotent: re-running clears prior handlers so worker processes that
    re-import this module don't end up with duplicate log lines.
    """

    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    resolved_service = service or os.getenv("SERVICE_NAME", "rt-ai-ids-api")
    resolved_schema = schema_version or os.getenv("LOG_SCHEMA_VERSION", "1.0")

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter(service=resolved_service, schema_version=resolved_schema))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)


def bind_correlation_id(correlation_id: str | None = None) -> str:
    """Bind a correlation id to the current context. Returns the bound id."""

    cid = correlation_id or uuid.uuid4().hex
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current context, if any."""

    return _correlation_id.get()
