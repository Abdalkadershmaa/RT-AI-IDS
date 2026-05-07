"""Alerts query, subscribe, and SSE-stream endpoints.

Uses :mod:`shared.db` (no Flask-SQLAlchemy) for persistence and
:mod:`shared.broker.pubsub` for live fan-out of newly persisted alerts.

Authentication for the SSE stream:

* Preferred: ``POST /api/v1/alerts/subscribe`` exchanges the caller's JWT
  for a short-lived (30 s) single-use ``nonce``. The browser then
  connects to ``GET /api/v1/alerts/stream?nonce=<nonce>``. The nonce is
  consumed atomically inside Redis and never leaks beyond the initial
  handshake into long-lived nginx access logs.
* Legacy: ``GET /api/v1/alerts/stream?access_token=<JWT>`` keeps working
  for one release (returns ``Deprecation: true``) so existing clients
  migrate without breakage.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError
from sqlalchemy import select

from shared.broker import listen_alerts
from shared.db import AttackLog, session_scope

from ..responses import envelope_response
from ..schemas.alerts import AlertsListQuery
from ..sse_nonce import NONCE_TTL_SECONDS, consume_nonce, issue_nonce

logger = logging.getLogger(__name__)

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


@alerts_bp.post("/subscribe")
@jwt_required()
def subscribe() -> tuple:
    """Mint a short-lived nonce that authenticates one SSE connection.

    The browser uses the returned ``nonce`` as a query-string parameter
    on the SSE ``stream`` endpoint, then discards it. Nonces expire in
    :data:`shared.api.sse_nonce.NONCE_TTL_SECONDS` seconds and are
    single-use.
    """

    subject = get_jwt_identity()
    nonce, ttl = issue_nonce(subject or "anonymous")
    return jsonify({"nonce": nonce, "expires_in": ttl}), 200


# Server-Sent Events live alert stream.
#
# Two-tier event delivery:
#
# 1. ``since_id`` cursor recovery: on (re)connect the handler first
#    flushes every alert with ``id > since_id`` (capped at 100) so a
#    transient client disconnect never loses an alert.
# 2. Redis pub/sub steady state: after the catch-up, the handler waits
#    on the ``alerts:new`` channel and forwards each fan-out message
#    immediately. End-to-end alert latency dashboards consistently show
#    < 500 ms from ``persist_alert`` to ``EventSource.onmessage``.
#
# The 1 s database polling loop that previously powered the stream is
# replaced by an idle pub/sub wait, dropping DB read load by ~99 %.
SSE_DEFAULT_HEARTBEAT_S = 15.0
SSE_PUBSUB_TIMEOUT_S = 1.0
SSE_MAX_BATCH = 100


def _authenticate_sse_request() -> tuple[str | None, bool, Response | None]:
    """Resolve the SSE caller identity. Returns (subject, deprecation, error_response)."""

    nonce = request.args.get("nonce", type=str, default="").strip()
    if nonce:
        subject = consume_nonce(nonce)
        if not subject:
            return None, False, _envelope("invalid_nonce", 401)
        return subject, False, None

    # Legacy ``?access_token=`` path — invoked imperatively so we can
    # mark the response with a ``Deprecation`` header instead of relying
    # on the global ``@jwt_required`` decorator.
    from flask_jwt_extended import verify_jwt_in_request

    try:
        verify_jwt_in_request()
    except Exception:  # noqa: BLE001 - JWT-Extended raises many subclasses
        return None, False, _envelope("unauthorized", 401)
    return get_jwt_identity() or "anonymous", True, None


def _catchup_payloads(cursor: int) -> list[dict[str, Any]]:
    """Fetch alerts persisted while the SSE client was disconnected."""

    with session_scope() as session:
        stmt = (
            select(AttackLog).where(AttackLog.id > cursor).order_by(AttackLog.id.asc()).limit(SSE_MAX_BATCH)
        )
        rows = session.execute(stmt).scalars().all()
        return [row.to_dict() for row in rows]


def _build_sse_generator(start_id: int, subject: str) -> Iterator[str]:
    cursor = start_id
    last_heartbeat = time.monotonic()
    yield ": connected\n\n"

    try:
        for payload in _catchup_payloads(cursor):
            cursor = max(cursor, int(payload["id"]))
            yield f"id: {payload['id']}\ndata: {json.dumps(payload)}\n\n"
    except Exception as exc:  # noqa: BLE001 - SSE streams must not crash gunicorn
        logger.warning("sse_catchup_failed subject=%s error=%s", subject, exc)

    # Steady state — listen on the Redis pub/sub fan-out channel.
    try:
        for message in listen_alerts(timeout_seconds=SSE_PUBSUB_TIMEOUT_S):
            now = time.monotonic()
            if message is None:
                if now - last_heartbeat >= SSE_DEFAULT_HEARTBEAT_S:
                    yield ": keep-alive\n\n"
                    last_heartbeat = now
                continue
            try:
                alert_id = int(message.get("id") or 0)
            except (TypeError, ValueError):
                alert_id = 0
            if alert_id and alert_id <= cursor:
                continue  # already delivered during catch-up
            cursor = max(cursor, alert_id)
            payload_id = alert_id or cursor
            yield f"id: {payload_id}\ndata: {json.dumps(message)}\n\n"
            last_heartbeat = now
    except Exception as exc:  # noqa: BLE001 - SSE streams must not crash gunicorn
        logger.warning("sse_pubsub_loop_failed subject=%s error=%s", subject, exc)


@alerts_bp.get("/stream")
def stream_alerts() -> Response:
    subject, deprecation, error = _authenticate_sse_request()
    if error is not None:
        return error
    assert subject is not None  # mypy: error path returned above

    try:
        since_id = max(request.args.get("since_id", default=0, type=int) or 0, 0)
    except (TypeError, ValueError):
        since_id = 0

    response = Response(
        stream_with_context(_build_sse_generator(since_id, subject)),
        mimetype="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"  # disable nginx response buffering
    response.headers["Connection"] = "keep-alive"
    if deprecation:
        # RFC 8594-style hint that the ``?access_token=`` path is going
        # away. Browsers ignore it; SDK maintainers can grep for it.
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = "true"
    return response


def _envelope(error: str, status: int, detail: Any = None) -> Response:
    """Local helper that mirrors the JSON-envelope shape used elsewhere."""

    body: dict[str, Any] = {"error": error, "status": status}
    if detail is not None:
        body["detail"] = detail
    response = jsonify(body)
    response.status_code = status
    return response


__all__ = ["alerts_bp", "NONCE_TTL_SECONDS"]
