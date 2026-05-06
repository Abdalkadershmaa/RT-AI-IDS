"""OpenTelemetry tracing primitives.

Tracing is best-effort: if the OTel SDK isn't installed or
``OTEL_EXPORTER_OTLP_ENDPOINT`` is empty, every helper becomes a no-op so
the application keeps working unchanged. Production deployments install
the OTel packages via ``requirements/api.txt`` and configure the endpoint
to point at their collector / Tempo / Jaeger.

The cross-service propagation contract is **W3C trace-context**: API
publishes ``traceparent`` (and optionally ``tracestate``) as fields on the
PredictJob payload; the inference worker reads them back and starts its
span as a continuation. This produces a single span tree spanning HTTP →
broker → worker → DB.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


_TRACING_AVAILABLE = False
_provider_initialised = False


try:  # pragma: no cover - optional in slim CI images
    from opentelemetry import context as otel_context
    from opentelemetry import trace
    from opentelemetry.propagate import extract, inject
    from opentelemetry.trace import SpanKind

    _TRACING_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover
    trace = None  # type: ignore[assignment]
    extract = None  # type: ignore[assignment]
    inject = None  # type: ignore[assignment]
    otel_context = None  # type: ignore[assignment]
    SpanKind = None  # type: ignore[assignment]
    logger.info(
        "opentelemetry_not_installed: tracing disabled. Install"
        " opentelemetry-sdk + opentelemetry-exporter-otlp-proto-http and"
        " set OTEL_EXPORTER_OTLP_ENDPOINT to enable distributed tracing."
    )


def configure_tracing(
    service_name: str,
    otlp_endpoint: str | None,
) -> None:
    """Initialise the global tracer provider exactly once per process.

    No-op when the SDK isn't installed or ``otlp_endpoint`` is empty. The
    second call from the same process is also a no-op (gunicorn workers
    re-enter ``create_app``).
    """

    global _provider_initialised
    if _provider_initialised:
        return
    if not _TRACING_AVAILABLE:
        return
    if not otlp_endpoint:
        # Without an exporter endpoint we still install a tracer provider
        # so the propagation context flows; spans are simply dropped.
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider

        resource = Resource.create({SERVICE_NAME: service_name})
        trace.set_tracer_provider(TracerProvider(resource=resource))
        _provider_initialised = True
        return

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(provider)
    _provider_initialised = True


def instrument_flask(app: Any) -> None:
    """Attach Flask request / response hooks to the global tracer provider.

    No-op when the SDK or the Flask integration isn't installed. Avoids
    re-instrumenting if called twice (idempotent).
    """

    if not _TRACING_AVAILABLE:
        return
    try:  # pragma: no cover - optional dependency
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
    except ModuleNotFoundError:
        return
    FlaskInstrumentor().instrument_app(app)


def instrument_sqlalchemy(engine: Any) -> None:
    """Attach SQLAlchemy query tracing if the integration is installed."""

    if not _TRACING_AVAILABLE:
        return
    try:  # pragma: no cover - optional dependency
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    except ModuleNotFoundError:
        return
    SQLAlchemyInstrumentor().instrument(engine=engine)


def inject_traceparent(carrier: dict[str, str]) -> dict[str, str]:
    """Stamp ``carrier`` with the current span's W3C trace-context headers.

    Mutates and returns ``carrier`` so callers can chain. Useful for embedding
    propagation into a broker payload that crosses process boundaries.
    """

    if not _TRACING_AVAILABLE:
        return carrier
    inject(carrier)  # type: ignore[misc]
    return carrier


def extracted_context(carrier: dict[str, str]) -> Any:
    """Reconstruct an OTel context from a propagation carrier."""

    if not _TRACING_AVAILABLE:
        return None
    return extract(carrier)  # type: ignore[misc]


@contextmanager
def start_consumer_span(name: str, carrier: dict[str, str] | None):
    """Start a CONSUMER span linked to the upstream context in ``carrier``.

    Used by the inference worker to continue the trace started by the API.
    No-op (yields ``None``) when the SDK is unavailable.
    """

    if not _TRACING_AVAILABLE:
        yield None
        return
    parent_ctx = extracted_context(carrier or {})
    tracer = trace.get_tracer(__name__)  # type: ignore[union-attr]
    token = otel_context.attach(parent_ctx)  # type: ignore[union-attr]
    try:
        with tracer.start_as_current_span(name, kind=SpanKind.CONSUMER) as span:
            yield span
    finally:
        otel_context.detach(token)  # type: ignore[union-attr]


def get_trace_id() -> str | None:
    """Return the current span's trace id as a 32-char hex string, or None."""

    if not _TRACING_AVAILABLE:
        return None
    span = trace.get_current_span()  # type: ignore[union-attr]
    if span is None:
        return None
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return f"{ctx.trace_id:032x}"


def get_span_id() -> str | None:
    """Return the current span's span id as a 16-char hex string, or None."""

    if not _TRACING_AVAILABLE:
        return None
    span = trace.get_current_span()  # type: ignore[union-attr]
    if span is None:
        return None
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return f"{ctx.span_id:016x}"


def is_available() -> bool:
    """True iff the OTel SDK is importable in this process."""

    return _TRACING_AVAILABLE
