"""Bootstrap-credential authentication endpoint."""

from __future__ import annotations

import hmac
from datetime import timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token
from pydantic import ValidationError

from shared.config import get_settings

from ..schemas.auth import TokenRequest

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


@auth_bp.post("/token")
def issue_token() -> tuple:
    """Exchange admin credentials for a short-lived JWT."""

    try:
        body = TokenRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        detail = [
            {"loc": ".".join(str(part) for part in err.get("loc", ())), "msg": err.get("msg", "")}
            for err in exc.errors(include_url=False, include_input=False)
        ]
        return jsonify({"error": "invalid_request", "detail": detail}), 400

    settings = get_settings()
    if hmac.compare_digest(body.username, settings.admin_username) and hmac.compare_digest(
        body.password, settings.admin_password
    ):
        token = create_access_token(identity=body.username, expires_delta=timedelta(hours=8))
        return jsonify({"access_token": token}), 200
    return jsonify({"error": "invalid_credentials"}), 401
