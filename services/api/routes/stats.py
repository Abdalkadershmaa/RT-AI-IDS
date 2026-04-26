"""Aggregate statistics endpoint."""

from __future__ import annotations

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import func, select

from shared.db import AttackLog, session_scope

stats_bp = Blueprint("stats", __name__, url_prefix="/api/v1")


@stats_bp.get("/stats")
@jwt_required()
def stats() -> tuple:
    with session_scope() as session:
        total_alerts = session.execute(select(func.count(AttackLog.id))).scalar_one()
        rows = session.execute(
            select(AttackLog.risk_label, func.count(AttackLog.id)).group_by(AttackLog.risk_label)
        ).all()
        risk_distribution = {label: count for label, count in rows}
    return jsonify({"total_alerts": total_alerts, "risk_distribution": risk_distribution}), 200
