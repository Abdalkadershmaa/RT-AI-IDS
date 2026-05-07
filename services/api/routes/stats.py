"""Aggregate statistics endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import func, select

from shared.db import AttackLog, session_scope
from shared.db.models import severity_for

stats_bp = Blueprint("stats", __name__, url_prefix="/api/v1")


# Public order of severity tiers for the dashboard's risk-distribution chart.
# Always returned in this order regardless of which buckets are populated so
# the frontend can render zero-counts as 0 without a separate fetch.
_SEVERITY_ORDER: tuple[str, ...] = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL")


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


@stats_bp.get("/stats/risk")
@jwt_required()
def stats_risk() -> tuple:
    """Severity-grouped alert counts for the dashboard's distribution chart.

    Always returns the five canonical severity tiers (CRITICAL → MINIMAL),
    even when a bucket has zero alerts, so the frontend can render the
    chart without a second round-trip. The shape matches the contract the
    dashboard's risk chart expects:

        {"risk_distribution": [{"label": "CRITICAL", "count": 12}, ...]}
    """

    with session_scope() as session:
        rows = session.execute(
            select(AttackLog.risk_label, func.count(AttackLog.id)).group_by(AttackLog.risk_label)
        ).all()

    counts: dict[str, int] = {label: 0 for label in _SEVERITY_ORDER}
    for risk_label, count in rows:
        severity = severity_for(risk_label)
        counts[severity] = counts.get(severity, 0) + int(count)

    distribution = [{"label": label, "count": counts[label]} for label in _SEVERITY_ORDER]
    return jsonify({"risk_distribution": distribution}), 200
