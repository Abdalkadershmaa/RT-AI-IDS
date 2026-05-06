"""Prometheus scrape endpoint.

Exposed at ``GET /api/v1/metrics`` without authentication so a Prometheus
server (typically running on the same private network) can scrape the
exporter directly. If you need to lock this down further, put the API
behind a reverse proxy that ACLs ``/api/v1/metrics`` to the prometheus
service IP / namespace.
"""

from __future__ import annotations

from flask import Blueprint, Response

from shared.config import get_settings
from shared.observability.metrics import is_available, render_latest

metrics_bp = Blueprint("metrics", __name__, url_prefix="/api/v1")


@metrics_bp.get("/metrics")
def metrics() -> Response:
    """Render the current registry in Prometheus text-exposition format."""

    settings = get_settings()
    if not settings.metrics_enabled or not is_available():
        return Response("metrics disabled\n", status=503, mimetype="text/plain")
    payload, content_type = render_latest()
    return Response(payload, status=200, mimetype=content_type)
