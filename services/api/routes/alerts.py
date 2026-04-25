from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from ..models import AttackLog

alerts_bp = Blueprint("alerts", __name__, url_prefix="/api/v1/alerts")


@alerts_bp.get("")
@jwt_required()
def list_alerts() -> tuple:
    limit = request.args.get("limit", default=50, type=int)
    limit = min(max(limit, 1), 500)
    records = AttackLog.query.order_by(AttackLog.created_at.desc()).limit(limit).all()
    return jsonify([record.to_dict() for record in records]), 200


@alerts_bp.get("/<int:alert_id>")
@jwt_required()
def get_alert(alert_id: int) -> tuple:
    record = AttackLog.query.get_or_404(alert_id)
    return jsonify(record.to_dict()), 200

