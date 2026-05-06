"""Verify the SOC SIEM log schema is stable.

Downstream parsers (Splunk / Elastic / Datadog) pin against the field set
documented in :mod:`shared.observability.logging`. These tests guard that
contract so a refactor doesn't silently rename or drop a key.
"""

from __future__ import annotations

import io
import json
import logging
from contextlib import redirect_stdout

from shared.observability import bind_correlation_id, configure_logging


def _emit_one_record(message: str = "predict_job_enqueued", **extra: object) -> dict:
    """Configure logging, emit one INFO line, capture and parse it."""

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        configure_logging("INFO", service="rt-ai-ids-api", schema_version="1.0")
        logger = logging.getLogger("test_logger")
        logger.info(message, extra=extra)
    raw = buffer.getvalue().strip().splitlines()[-1]
    return json.loads(raw)


def test_required_keys_present_on_every_record() -> None:
    record = _emit_one_record()
    for key in (
        "ts",
        "schema_version",
        "service",
        "level",
        "logger",
        "event",
        "message",
    ):
        assert key in record, f"missing required key: {key}"


def test_schema_version_pinned_to_configured_value() -> None:
    record = _emit_one_record()
    assert record["schema_version"] == "1.0"


def test_service_name_is_propagated() -> None:
    record = _emit_one_record()
    assert record["service"] == "rt-ai-ids-api"


def test_event_defaults_to_message_when_extra_omitted() -> None:
    record = _emit_one_record(message="predict_job_enqueued")
    assert record["event"] == "predict_job_enqueued"
    assert record["message"] == "predict_job_enqueued"


def test_extra_kwargs_are_passed_through_verbatim() -> None:
    record = _emit_one_record(
        message="predict_job_enqueued",
        job_id="abc123",
        flow_id="flow-1",
        risk_label="HIGH",
    )
    assert record["job_id"] == "abc123"
    assert record["flow_id"] == "flow-1"
    assert record["risk_label"] == "HIGH"


def test_correlation_id_is_emitted_when_bound() -> None:
    bind_correlation_id("corr-xyz")
    try:
        record = _emit_one_record()
    finally:
        bind_correlation_id("")  # reset to a safe empty value
    assert record["correlation_id"] == "corr-xyz"


def test_unserialisable_extras_fall_back_to_repr() -> None:
    class _NotJsonable:
        def __repr__(self) -> str:
            return "<NotJsonable>"

    record = _emit_one_record(message="event", weird=_NotJsonable())
    assert record["weird"] == "<NotJsonable>"
