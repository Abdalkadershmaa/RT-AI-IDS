"""Health and readiness probes."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify
from sqlalchemy import text

from shared.db import get_engine

health_bp = Blueprint("health", __name__, url_prefix="/api/v1")
logger = logging.getLogger(__name__)


@health_bp.get("/health")
def health() -> tuple:
    """Liveness probe — returns 200 as long as the process is up."""

    return jsonify({"status": "ok"}), 200


@health_bp.get("/ready")
def ready() -> tuple:
    """Readiness probe — verifies database connectivity."""

    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("readiness_check_failed error=%s", exc)
        return jsonify({"status": "not_ready"}), 503
    return jsonify({"status": "ready"}), 200
