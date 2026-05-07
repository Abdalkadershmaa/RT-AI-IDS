"""Cross-service observability primitives.

Three layers, all designed to fail open when their backing libraries aren't
installed (so slim CI test images don't need the full observability
toolchain):

* :mod:`shared.observability.logging` — structured JSON logs with a stable
  SIEM-friendly schema (always available).
* :mod:`shared.observability.metrics` — Prometheus exporter (optional;
  metrics become no-ops without ``prometheus_client``).
* :mod:`shared.observability.tracing` — OpenTelemetry tracing (optional;
  no-op without the OTel SDK or when no exporter endpoint is configured).
"""

from .logging import bind_correlation_id, configure_logging, get_correlation_id

__all__ = [
    "bind_correlation_id",
    "configure_logging",
    "get_correlation_id",
]
