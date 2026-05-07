"""Verify the API-side OTel propagation contract.

The contract is: when an HTTP request enters the API, ``inject_traceparent``
stamps the current trace-context onto the PredictJob payload as the
``traceparent`` (and optionally ``tracestate``) field. The inference worker
later reads it back via :func:`start_consumer_span`.

Without the OTel SDK installed both helpers are no-ops, which is also a
contractually correct outcome — these tests assert the no-op behaviour
when the SDK is missing and the propagation behaviour when it isn't.
"""

from __future__ import annotations

import pytest

from shared.observability import tracing


def test_inject_traceparent_returns_carrier_dict() -> None:
    carrier: dict[str, str] = {}
    out = tracing.inject_traceparent(carrier)
    assert out is carrier


def test_get_trace_id_returns_none_outside_span_when_sdk_missing() -> None:
    if tracing.is_available():
        pytest.skip("OTel SDK installed; outside-span behaviour differs")
    assert tracing.get_trace_id() is None
    assert tracing.get_span_id() is None


def test_start_consumer_span_yields_none_when_sdk_missing() -> None:
    if tracing.is_available():
        pytest.skip("OTel SDK installed; the span object is non-None")
    with tracing.start_consumer_span("test", carrier=None) as span:
        assert span is None


def test_inject_traceparent_writes_w3c_header_when_sdk_available() -> None:
    pytest.importorskip("opentelemetry", reason="opentelemetry-sdk not installed in this env")
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider

    tracer_provider = otel_trace.get_tracer_provider()
    if not isinstance(tracer_provider, TracerProvider):
        otel_trace.set_tracer_provider(TracerProvider())

    tracer = otel_trace.get_tracer("test")
    with tracer.start_as_current_span("api.predict"):
        carrier: dict[str, str] = {}
        tracing.inject_traceparent(carrier)
        assert "traceparent" in carrier
        # W3C trace-context format: 00-<trace_id>-<span_id>-<flags>
        parts = carrier["traceparent"].split("-")
        assert len(parts) == 4
        assert parts[0] == "00"
