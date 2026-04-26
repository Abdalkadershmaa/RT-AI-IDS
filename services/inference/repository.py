"""Persistence helpers for inference results. Flask-free."""

from __future__ import annotations

from typing import Any

from shared.db import AttackLog, session_scope
from shared.schemas import DetectionResult


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def persist_alert(result: DetectionResult, context: dict[str, Any]) -> AttackLog:
    """Persist a :class:`DetectionResult` and return the saved row (detached)."""

    record = AttackLog(
        flow_id=result.flow_id,
        source_ip=str(context.get("src_ip", "")),
        source_port=_safe_int(context.get("src_port", 0)),
        destination_ip=str(context.get("dst_ip", "")),
        destination_port=_safe_int(context.get("dst_port", 0)),
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
        # Materialize fields before the session closes so callers can use the
        # detached instance freely.
        snapshot = record.to_dict()
    record.id = snapshot["id"]
    return record
