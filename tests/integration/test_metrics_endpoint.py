"""Integration tests for the Prometheus scrape endpoint.

The endpoint at ``GET /api/v1/metrics`` is unauthenticated by design so a
Prometheus scraper on the same private network can poll it without any
token plumbing. These tests cover both the available and unavailable
states of ``prometheus_client`` so the slim CI image still passes.
"""

from __future__ import annotations

import pytest

from shared.observability import metrics


def test_metrics_endpoint_skips_auth(api_client) -> None:
    response = api_client.get("/api/v1/metrics")
    # 200 when prometheus_client is installed; 503 when it's the noop fallback.
    assert response.status_code in {200, 503}


def test_metrics_endpoint_returns_503_when_disabled(api_client, monkeypatch) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "false")
    from shared.config import reload_settings

    reload_settings()

    response = api_client.get("/api/v1/metrics")
    assert response.status_code == 503
    assert b"metrics disabled" in response.data


def test_metrics_endpoint_returns_text_exposition_format(api_client) -> None:
    if not metrics.is_available():
        pytest.skip("prometheus_client not installed; skipping format check")

    response = api_client.get("/api/v1/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.content_type


def test_metrics_endpoint_excluded_from_its_own_counters(api_client) -> None:
    if not metrics.is_available():
        pytest.skip("prometheus_client not installed; skipping counter check")

    # Hit the metrics endpoint twice; rt_ai_ids_http_requests_total
    # should NOT include `endpoint="metrics.metrics"` in the output.
    api_client.get("/api/v1/metrics")
    response = api_client.get("/api/v1/metrics")
    text = response.data.decode("utf-8")
    assert 'endpoint="metrics.metrics"' not in text


def test_http_counter_increments_on_request(api_client) -> None:
    if not metrics.is_available():
        pytest.skip("prometheus_client not installed; counter is a no-op")

    # /health is unauthenticated so it's a stable counter target.
    api_client.get("/api/v1/health")
    response = api_client.get("/api/v1/metrics")
    text = response.data.decode("utf-8")
    assert "rt_ai_ids_http_requests_total" in text
    assert 'endpoint="health.health"' in text
