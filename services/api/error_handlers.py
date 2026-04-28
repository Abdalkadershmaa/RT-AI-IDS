"""Uniform JSON error responses + JWT-aware status codes.

Every error returned by the API conforms to the envelope defined in
:mod:`services.api.responses`. Framework-generated errors (404 from an
unknown route, 405 from a wrong method, 422 from missing JSON, 429 from
the rate limiter, 500 from an unhandled exception) all flow through this
module.
"""

from __future__ import annotations

import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

from .extensions import jwt
from .responses import envelope_response

logger = logging.getLogger(__name__)


def _http_envelope(error: HTTPException):  # type: ignore[no-untyped-def]
    """Translate any :class:`werkzeug.HTTPException` into the canonical envelope.

    The error code is the lowercased, underscore-joined ``HTTPException.name``
    (e.g. ``"too_many_requests"`` for 429), and the description is forwarded
    as ``detail`` so callers see exactly the message Werkzeug attached.
    """

    code = error.name.lower().replace(" ", "_") if error.name else "http_error"
    return envelope_response(code, error.code or 500, error.description)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def _http(error: HTTPException):  # type: ignore[no-untyped-def]
        return _http_envelope(error)

    @app.errorhandler(Exception)
    def _unhandled(error: Exception):  # type: ignore[no-untyped-def]
        if isinstance(error, HTTPException):
            return _http_envelope(error)
        logger.exception("unhandled_exception")
        return envelope_response("internal_server_error", 500)

    @jwt.unauthorized_loader
    def _missing_token(reason: str):  # type: ignore[no-untyped-def]
        return envelope_response("unauthorized", 401, reason)

    @jwt.invalid_token_loader
    def _invalid_token(reason: str):  # type: ignore[no-untyped-def]
        return envelope_response("invalid_token", 401, reason)

    @jwt.expired_token_loader
    def _expired_token(_header, _payload):  # type: ignore[no-untyped-def]
        return envelope_response("expired_token", 401)
