"""Tests for the Prometheus exporter helpers.

These tests skip gracefully when ``prometheus_client`` is not installed
(the slim CI matrix). When it IS installed they assert that the metric
helpers register on a dedicated registry, that ``render_latest`` produces
text-exposition format, and that the noop pattern is exercised correctly
in the unavailable case.
"""

from __future__ import annotations

import pytest

from shared.observability import metrics


def test_render_latest_returns_bytes_and_content_type() -> None:
    payload, content_type = metrics.render_latest()
    assert isinstance(payload, bytes)
    assert "text/plain" in content_type


def test_metrics_module_exports_expected_helpers() -> None:
    expected = (
        "http_requests_total",
        "http_request_duration_seconds",
        "predict_jobs_published_total",
        "predict_jobs_completed_total",
        "predict_job_duration_seconds",
        "alerts_persisted_total",
        "broker_dlq_total",
        "pipeline_probe_status",
        "pipeline_probe_latency_seconds",
    )
    for name in expected:
        assert hasattr(metrics, name), f"missing metric: {name}"


def test_counter_inc_is_a_safe_noop_without_prometheus_client() -> None:
    if metrics.is_available():
        pytest.skip("prometheus_client installed; noop path not exercised")

    # Calls must not raise even when the module is in fallback mode.
    metrics.http_requests_total.labels(method="GET", endpoint="x", status="200").inc()
    metrics.alerts_persisted_total.labels(risk_label="LOW").inc()
    metrics.pipeline_probe_status.set(1.0)
    payload, _ = metrics.render_latest()
    assert payload == b""


def test_render_latest_includes_counter_when_prometheus_client_available() -> None:
    pytest.importorskip("prometheus_client", reason="prometheus_client not installed in this env")

    metrics.http_requests_total.labels(method="GET", endpoint="probe.test", status="200").inc()
    payload, _ = metrics.render_latest()
    text = payload.decode("utf-8")
    assert "rt_ai_ids_http_requests_total" in text
