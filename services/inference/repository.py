"""Persistence helpers for inference results. Flask-free.

Public API context fields are ``source_ip`` / ``source_port`` /
``destination_ip`` / ``destination_port`` to match the response payload and
the database column names. Internal flow-pipeline events still emit
``src_ip`` / ``dst_ip`` (matching :class:`shared.schemas.events.PacketEvent`),
so we accept both shapes here and prefer the canonical names when both are
present.
"""

from __future__ import annotations

from typing import Any

from shared.db import AttackLog, session_scope
from shared.schemas import DetectionResult


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coalesce(context: dict[str, Any], *names: str, default: Any = "") -> Any:
    """Return the first non-empty context value among ``names``."""

    for name in names:
        value = context.get(name)
        if value not in (None, ""):
            return value
    return default


def persist_alert(result: DetectionResult, context: dict[str, Any]) -> int:
    """Persist a :class:`DetectionResult` and return the new row's primary key."""

    record = AttackLog(
        flow_id=result.flow_id,
        source_ip=str(_coalesce(context, "source_ip", "src_ip", default="")),
        source_port=_safe_int(_coalesce(context, "source_port", "src_port", default=0)),
        destination_ip=str(_coalesce(context, "destination_ip", "dst_ip", default="")),
        destination_port=_safe_int(
            _coalesce(context, "destination_port", "dst_port", default=0)
        ),
        protocol=str(context.get("protocol", "")),
        classification=result.classification,
        probability=result.probability,
        risk_label=result.risk_label,
        risk_score=result.risk_score,
        rationale=list(result.rationale),
    )
    with session_scope() as session:
        session.add(record)
        session.flush()
        new_id = int(record.id)
    return new_id
