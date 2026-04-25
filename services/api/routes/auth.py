import hmac
from datetime import timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token

from shared.config import get_settings

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


@auth_bp.post("/token")
def issue_token() -> tuple:
    body = request.get_json(silent=True) or {}
    username = body.get("username", "")
    password = body.get("password", "")
    settings = get_settings()

    if hmac.compare_digest(str(username), settings.admin_username) and hmac.compare_digest(
        str(password),
        settings.admin_password,
    ):
        token = create_access_token(identity=username, expires_delta=timedelta(hours=8))
        return jsonify({"access_token": token}), 200
    return jsonify({"error": "invalid_credentials"}), 401

