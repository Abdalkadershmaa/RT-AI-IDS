import logging

from flask import Blueprint, jsonify

from ..extensions import db

health_bp = Blueprint("health", __name__, url_prefix="/api/v1")
logger = logging.getLogger(__name__)


@health_bp.get("/health")
def health() -> tuple:
    return jsonify({"status": "ok"}), 200


@health_bp.get("/ready")
def ready() -> tuple:
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception as exc:
        logger.warning("readiness_check_failed error=%s", exc)
        return jsonify({"status": "not_ready"}), 503
    return jsonify({"status": "ready"}), 200

