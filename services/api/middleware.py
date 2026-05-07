"""HTTP middleware for request-level observability.

Single concern: emit Prometheus counters + histograms for every Flask
request, labelled by ``method``, ``endpoint`` (route rule, NOT raw path —
high-cardinality paths like ``/api/v1/alerts/<id>`` collapse to the single
rule ``alerts.alert_detail``), and ``status``.

The middleware is installed by :func:`install_metrics_middleware` from the
Flask app factory. Tracing instrumentation is wired separately in
:mod:`shared.observability.tracing`.
"""

from __future__ import annotations

import time
from typing import Any

from flask import Flask, g, request

from shared.observability.metrics import (
    http_request_duration_seconds,
    http_requests_total,
)

# Endpoints we deliberately omit from metrics. Scraping ``/metrics`` itself
# would cause every Prometheus poll to bump its own counter, which is both
# noisy and makes RPS dashboards lie about real traffic.
_EXCLUDED_ENDPOINTS = {"metrics.metrics"}


def install_metrics_middleware(app: Flask) -> None:
    """Wire request-timing + counter middleware onto the Flask app."""

    @app.before_request
    def _record_start() -> None:  # type: ignore[no-untyped-def]
        g._metrics_start = time.perf_counter()

    @app.after_request
    def _record_end(response: Any):  # type: ignore[no-untyped-def]
        endpoint = request.endpoint or "unknown"
        if endpoint in _EXCLUDED_ENDPOINTS:
            return response

        method = request.method
        status = str(response.status_code)
        http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()

        start = getattr(g, "_metrics_start", None)
        if start is not None:
            elapsed = time.perf_counter() - start
            http_request_duration_seconds.labels(method=method, endpoint=endpoint, status=status).observe(
                elapsed
            )
        return response
