"""Prometheus metrics primitives.

The exporter is intentionally optional: if ``prometheus_client`` is not
installed (e.g. the slim CI matrix), every metric becomes a no-op stub so
the rest of the application keeps working. Production deployments install
``prometheus_client`` via ``requirements/api.txt`` and friends.

Conventions:
- All metric names use the ``rt_ai_ids_`` prefix so dashboards can pick the
  service out of a multi-tenant Prometheus.
- Histograms cover latency in seconds with the standard SRE buckets.
- Labels are kept low-cardinality on purpose — never label by ``job_id``,
  ``flow_id``, ``source_ip``, etc.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


try:  # pragma: no cover - optional in slim CI images
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROMETHEUS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised only when missing
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"  # type: ignore[assignment]
    CollectorRegistry = None  # type: ignore[assignment]
    Counter = None  # type: ignore[assignment]
    Gauge = None  # type: ignore[assignment]
    Histogram = None  # type: ignore[assignment]

    def generate_latest(_registry: Any | None = None) -> bytes:  # type: ignore[no-redef]
        return b""

    _PROMETHEUS_AVAILABLE = False
    logger.warning(
        "prometheus_client_not_installed: metrics endpoint will return 503."
        " Install prometheus-client (already in requirements/api.txt) to"
        " enable scrape-format metrics."
    )


_HTTP_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class _NoopMetric:
    """Stub used when prometheus_client is unavailable.

    Every method is a no-op so call sites never have to guard with
    ``if _PROMETHEUS_AVAILABLE:`` — they can just call ``inc()`` /
    ``observe()`` / ``labels(...)`` unconditionally.
    """

    def labels(self, *_args: Any, **_kwargs: Any) -> _NoopMetric:
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def dec(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def observe(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _make_registry() -> Any:
    if not _PROMETHEUS_AVAILABLE:
        return None
    return CollectorRegistry()


def _counter(name: str, documentation: str, labelnames: list[str]) -> Any:
    if not _PROMETHEUS_AVAILABLE:
        return _NoopMetric()
    return Counter(name, documentation, labelnames=labelnames, registry=registry)


def _gauge(name: str, documentation: str, labelnames: list[str] | None = None) -> Any:
    if not _PROMETHEUS_AVAILABLE:
        return _NoopMetric()
    return Gauge(name, documentation, labelnames=labelnames or [], registry=registry)


def _histogram(name: str, documentation: str, labelnames: list[str], buckets: tuple) -> Any:
    if not _PROMETHEUS_AVAILABLE:
        return _NoopMetric()
    return Histogram(name, documentation, labelnames=labelnames, buckets=buckets, registry=registry)


# A dedicated registry is intentionally used (rather than the default global
# one) so multi-process gunicorn deploys can swap in
# ``MultiProcessCollector`` without leaking the default Counter / Gauge
# instances created elsewhere in the dependency tree.
registry: Any = _make_registry()


http_requests_total = _counter(
    "rt_ai_ids_http_requests_total",
    "HTTP requests handled by the API service.",
    labelnames=["method", "endpoint", "status"],
)

http_request_duration_seconds = _histogram(
    "rt_ai_ids_http_request_duration_seconds",
    "Wall-clock latency of HTTP requests in seconds.",
    labelnames=["method", "endpoint", "status"],
    buckets=_HTTP_LATENCY_BUCKETS,
)

predict_jobs_published_total = _counter(
    "rt_ai_ids_predict_jobs_published_total",
    "Predict jobs published to the broker by the API.",
    labelnames=["status"],
)

predict_jobs_completed_total = _counter(
    "rt_ai_ids_predict_jobs_completed_total",
    "Predict jobs completed by the inference worker.",
    labelnames=["status"],
)

predict_job_duration_seconds = _histogram(
    "rt_ai_ids_predict_job_duration_seconds",
    "Inference latency per predict job in seconds.",
    labelnames=["status"],
    buckets=_HTTP_LATENCY_BUCKETS,
)

alerts_persisted_total = _counter(
    "rt_ai_ids_alerts_persisted_total",
    "Alerts persisted to the attack_logs table.",
    labelnames=["risk_label"],
)

broker_dlq_total = _counter(
    "rt_ai_ids_broker_dlq_total",
    "Messages routed to a stream's dead-letter queue after exhausting retries.",
    labelnames=["stream"],
)

pipeline_probe_status = _gauge(
    "rt_ai_ids_pipeline_probe_status",
    "End-to-end pipeline probe status. 1=ok, 0.5=degraded, 0=down.",
)

pipeline_probe_latency_seconds = _gauge(
    "rt_ai_ids_pipeline_probe_latency_seconds",
    "Wall-clock latency of the most recent pipeline probe.",
)


def render_latest() -> tuple[bytes, str]:
    """Render the current metric registry in Prometheus text-exposition format.

    Returns
    -------
    (payload, content_type)
        Tuple ready to drop into a Flask response. When prometheus_client is
        unavailable, ``payload`` is empty and the caller should return 503.
    """

    if not _PROMETHEUS_AVAILABLE or registry is None:
        return b"", CONTENT_TYPE_LATEST
    return generate_latest(registry), CONTENT_TYPE_LATEST


def is_available() -> bool:
    """True iff prometheus_client is importable in this process."""

    return _PROMETHEUS_AVAILABLE
