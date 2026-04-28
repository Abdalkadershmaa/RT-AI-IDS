"""Bootstrap-credential authentication endpoint.

The token endpoint is rate-limited (see :mod:`services.api.extensions`) so
brute-force attempts against the bootstrap admin account return 429 long
before the credential check runs. Successful and failed responses share the
same envelope shape as the rest of the API.
"""

from __future__ import annotations

import hmac
from datetime import timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token
from pydantic import ValidationError

from shared.config import get_settings

from ..extensions import limiter
from ..responses import envelope_response
from ..schemas.auth import TokenRequest

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


def _auth_rate_limit() -> str:
    """Read the configured limit at call time so tests can override it."""

    return get_settings().auth_rate_limit


@auth_bp.post("/token")
@limiter.limit(_auth_rate_limit)
def issue_token() -> tuple:
    """Exchange admin credentials for a short-lived JWT."""

    try:
        body = TokenRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        detail = [
            {"loc": ".".join(str(part) for part in err.get("loc", ())), "msg": err.get("msg", "")}
            for err in exc.errors(include_url=False, include_input=False)
        ]
        return envelope_response("invalid_request", 400, detail)

    settings = get_settings()
    if hmac.compare_digest(body.username, settings.admin_username) and hmac.compare_digest(
        body.password, settings.admin_password
    ):
        token = create_access_token(identity=body.username, expires_delta=timedelta(hours=8))
        return jsonify({"access_token": token}), 200
    return envelope_response("invalid_credentials", 401)
