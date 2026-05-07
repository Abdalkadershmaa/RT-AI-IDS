"""Alerts query endpoints. Uses :mod:`shared.db` (no Flask-SQLAlchemy)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

from flask import Blueprint, Response, jsonify, request, stream_with_context
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


# Server-Sent Events live alert stream.
#
# Browser ``EventSource`` cannot send custom request headers, so this endpoint
# accepts the JWT via ``?access_token=...`` (configured globally in
# ``services.api.app``). The handler tails the database with a small ``id``
# cursor, sleeping ``poll_interval_s`` between scans. Every new row is emitted
# as one SSE ``data: {alert_json}`` frame plus a heartbeat comment every
# ``heartbeat_s`` seconds so proxies don't drop the idle connection.
#
# Latency: at the default 1 s poll interval, an alert lands on the dashboard
# at most ~1 s after it is written to ``attack_logs`` — comfortably inside the
# 5 s end-to-end budget agreed for the live demo.
SSE_DEFAULT_POLL_INTERVAL_S = 1.0
SSE_DEFAULT_HEARTBEAT_S = 15.0
SSE_MAX_BATCH = 100


@alerts_bp.get("/stream")
@jwt_required()
def stream_alerts() -> Response:
    try:
        since_id = request.args.get("since_id", default=0, type=int)
    except (TypeError, ValueError):
        since_id = 0
    since_id = max(since_id, 0)

    poll_interval = SSE_DEFAULT_POLL_INTERVAL_S
    heartbeat = SSE_DEFAULT_HEARTBEAT_S

    @stream_with_context
    def _generate(start_id: int) -> Iterator[str]:
        cursor = start_id
        last_heartbeat = time.monotonic()
        # Initial comment so EventSource fires its onopen handler promptly.
        yield ": connected\n\n"
        while True:
            with session_scope() as session:
                stmt = (
                    select(AttackLog)
                    .where(AttackLog.id > cursor)
                    .order_by(AttackLog.id.asc())
                    .limit(SSE_MAX_BATCH)
                )
                rows = session.execute(stmt).scalars().all()
                payloads = [row.to_dict() for row in rows]
            for payload in payloads:
                cursor = max(cursor, int(payload["id"]))
                yield f"id: {payload['id']}\ndata: {json.dumps(payload)}\n\n"
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat:
                yield ": keep-alive\n\n"
                last_heartbeat = now
            time.sleep(poll_interval)

    response = Response(_generate(since_id), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"  # disable nginx response buffering
    response.headers["Connection"] = "keep-alive"
    return response
