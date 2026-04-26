"""Uniform JSON error responses + JWT-aware status codes."""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .extensions import jwt

logger = logging.getLogger(__name__)


def _envelope(error: str, status: int, detail: Any | None = None) -> tuple:
    body: dict[str, Any] = {"error": error, "status": status}
    if detail is not None:
        body["detail"] = detail
    return jsonify(body), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def _http(error: HTTPException):  # type: ignore[no-untyped-def]
        return _envelope(error.name.lower().replace(" ", "_"), error.code or 500, error.description)

    @app.errorhandler(404)
    def _not_found(_error):  # type: ignore[no-untyped-def]
        return _envelope("not_found", 404)

    @app.errorhandler(400)
    def _bad_request(_error):  # type: ignore[no-untyped-def]
        return _envelope("bad_request", 400)

    @app.errorhandler(Exception)
    def _unhandled(error: Exception):  # type: ignore[no-untyped-def]
        if isinstance(error, HTTPException):
            return _http(error)
        logger.exception("unhandled_exception")
        return _envelope("internal_server_error", 500)

    @jwt.unauthorized_loader
    def _missing_token(reason: str):  # type: ignore[no-untyped-def]
        return _envelope("unauthorized", 401, reason)

    @jwt.invalid_token_loader
    def _invalid_token(reason: str):  # type: ignore[no-untyped-def]
        return _envelope("invalid_token", 401, reason)

    @jwt.expired_token_loader
    def _expired_token(_header, _payload):  # type: ignore[no-untyped-def]
        return _envelope("expired_token", 401)
