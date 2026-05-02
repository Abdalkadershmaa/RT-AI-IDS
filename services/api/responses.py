"""Shared response helpers for Flask routes.

The API publishes a single error envelope shape — ``{error, status, detail?}``
— so frontend, mobile, and ops dashboards can parse failures with one model.
This module centralizes envelope construction so individual route handlers
don't drift over time.

The same shape is emitted by:

* :mod:`services.api.error_handlers` for framework-level errors (404, 405,
  422, 500, JWT failures, rate-limit 429).
* Every blueprint in :mod:`services.api.routes` for application-level
  failures (validation errors, business-rule rejections).
"""

from __future__ import annotations

from typing import Any

from flask import Response, jsonify


def envelope_response(error: str, status: int, detail: Any | None = None) -> tuple[Response, int]:
    """Build a JSON error response with the canonical envelope shape.

    Parameters
    ----------
    error:
        Stable machine-readable code (snake_case). Frontend code keys off
        this — never localize it.
    status:
        HTTP status code, also embedded in the body so consumers don't need
        to inspect the response status separately.
    detail:
        Optional human-readable extra context. Strings, lists of validation
        issues, and free-form dicts are all accepted; ``None`` omits the
        field entirely.
    """

    body: dict[str, Any] = {"error": error, "status": status}
    if detail is not None:
        body["detail"] = detail
    return jsonify(body), status
