"""Alerts query endpoints. Uses :mod:`shared.db` (no Flask-SQLAlchemy)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import select

from shared.db import AttackLog, session_scope

from ..schemas.alerts import AlertsListQuery

alerts_bp = Blueprint("alerts", __name__, url_prefix="/api/v1/alerts")


@alerts_bp.get("")
@jwt_required()
def list_alerts() -> tuple:
    query = AlertsListQuery(limit=request.args.get("limit", default=50, type=int))
    with session_scope() as session:
        records = (
            session.execute(
                select(AttackLog).order_by(AttackLog.created_at.desc()).limit(query.limit)
            )
            .scalars()
            .all()
        )
        payload = [record.to_dict() for record in records]
    return jsonify(payload), 200


@alerts_bp.get("/<int:alert_id>")
@jwt_required()
def get_alert(alert_id: int) -> tuple:
    with session_scope() as session:
        record = session.get(AttackLog, alert_id)
        if record is None:
            return jsonify({"error": "not_found"}), 404
        payload = record.to_dict()
    return jsonify(payload), 200
