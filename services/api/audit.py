"""Helpers for writing audit-log rows.

Every privileged action (admin endpoints today, tenant lifecycle in
Phase 3, license extension/suspension, plan changes) calls
:func:`record_audit_event` to append an immutable row to ``audit_logs``.
The helper deliberately swallows persistence errors and logs them, so a
flaky DB does not turn an admin response into a 500 — auditing is
best-effort durable but never breaks the request handler.
"""

from __future__ import annotations

import logging
from typing import Any

from shared.db import AuditLog, session_scope

logger = logging.getLogger(__name__)


def record_audit_event(
    *,
    actor: str | None,
    action: str,
    target: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int | None:
    """Persist an audit-log row. Returns the new row id, or ``None`` on failure."""

    try:
        record = AuditLog(
            actor=actor,
            action=action,
            target=target,
            payload=dict(payload or {}),
        )
        with session_scope() as session:
            session.add(record)
            session.flush()
            new_id = int(record.id) if record.id is not None else None
        logger.info(
            "audit_event_recorded",
            extra={
                "audit_id": new_id,
                "actor": actor,
                "action": action,
                "target": target,
            },
        )
        return new_id
    except Exception as exc:  # noqa: BLE001 - audit must never crash the caller
        logger.exception("audit_event_persist_failed action=%s actor=%s error=%s", action, actor, exc)
        return None
