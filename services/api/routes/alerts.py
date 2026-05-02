"""Alerts query endpoints. Uses :mod:`shared.db` (no Flask-SQLAlchemy)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from pydantic import ValidationError
from sqlalchemy import select

from shared.db import AttackLog, session_scope

from ..responses import envelope_response
from ..schemas.alerts import AlertsListQuery

alerts_bp = Blueprint("alerts", __name__, url_prefix="/api/v1/alerts")


@alerts_bp.get("")
@jwt_required()
def list_alerts() -> tuple:
    try:
        query = AlertsListQuery(
            limit=request.args.get("limit", default=50, type=int),
            since_id=request.args.get("since_id", default=None, type=int),
            before_id=request.args.get("before_id", default=None, type=int),
            risk_label=request.args.get("risk_label", default=None, type=str),
        )
    except ValidationError:
        return envelope_response("invalid_request", 400)

    if query.since_id is not None and query.before_id is not None:
        return envelope_response(
            "invalid_request",
            400,
            "since_id and before_id are mutually exclusive",
        )

    stmt = select(AttackLog)
    if query.risk_label is not None:
        stmt = stmt.where(AttackLog.risk_label == query.risk_label)
    if query.since_id is not None:
        # Delta polling: rows newer than the cursor, ordered ascending so
        # the client can append in chronological order.
        stmt = stmt.where(AttackLog.id > query.since_id).order_by(AttackLog.id.asc())
    elif query.before_id is not None:
        # Infinite-scroll older history: rows older than the cursor,
        # ordered newest-first like the default.
        stmt = stmt.where(AttackLog.id < query.before_id).order_by(AttackLog.id.desc())
    else:
        stmt = stmt.order_by(AttackLog.created_at.desc(), AttackLog.id.desc())

    stmt = stmt.limit(query.limit)

    with session_scope() as session:
        records = session.execute(stmt).scalars().all()
        payload = [record.to_dict() for record in records]
    return jsonify(payload), 200


@alerts_bp.get("/<int:alert_id>")
@jwt_required()
def get_alert(alert_id: int) -> tuple:
    with session_scope() as session:
        record = session.get(AttackLog, alert_id)
        if record is None:
            return envelope_response("not_found", 404)
        payload = record.to_dict()
    return jsonify(payload), 200
