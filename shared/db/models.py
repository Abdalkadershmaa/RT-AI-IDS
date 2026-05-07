"""ORM models. Framework-agnostic — usable from any service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Float, Index, Integer, String, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base used by every ORM model in the project."""


# Map the broker's lowercase ``risk_label`` to the uppercase severity tier
# the frontend / Chrome extension / SIEM-shipper consumers expect. Kept here
# (next to ``AttackLog``) so every consumer of the alert dict gets the same
# canonical mapping.
_RISK_LABEL_TO_SEVERITY: dict[str, str] = {
    "very_high": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "minimal": "MINIMAL",
}


def severity_for(risk_label: str | None) -> str:
    """Return the uppercase severity tier for an alert's ``risk_label``."""

    if not risk_label:
        return "MINIMAL"
    return _RISK_LABEL_TO_SEVERITY.get(risk_label.lower(), risk_label.upper())


class AttackLog(Base):
    """Persisted prediction. One row per inference result."""

    __tablename__ = "attack_logs"
    __table_args__ = (
        Index("ix_attack_logs_created_at_id", "created_at", "id"),
        Index("ix_attack_logs_risk_label_created_at", "risk_label", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_ip: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_port: Mapped[int] = mapped_column(Integer, nullable=False)
    destination_ip: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    destination_port: Mapped[int] = mapped_column(Integer, nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), nullable=False)
    classification: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    risk_label: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Per-row LIME attribution rendered as a list of ``{feature, weight}``
    # objects. Empty list means the explainer was unavailable, the budget
    # was exceeded, or the row predates end-to-end LIME wiring.
    explanation: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    # Metadata about the model that produced this alert. Captured per-row so
    # historical alerts remain traceable to a specific model build even after
    # the live model is retrained / rolled forward. Nullable for rows that
    # predate the column (existing deployments back-filled by migration).
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_dataset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        nullable=False,
        index=True,
    )

    def to_dict(self) -> dict[str, Any]:
        """Render an alert as a JSON-serializable dict for API responses.

        Adds three additive fields that the frontend / Chrome extension /
        Predict page UI consume directly:

        * ``severity`` — uppercase tier mapped from ``risk_label``.
        * ``type``     — alias of ``classification`` (frontend's chosen name).
        * ``confidence`` — ``probability * 100`` rounded to one decimal place.
        * ``explanation`` — LIME attribution list, ``[]`` if unavailable.
        """

        explanation = list(self.explanation or [])
        return {
            "id": self.id,
            "flow_id": self.flow_id,
            "source_ip": self.source_ip,
            "source_port": self.source_port,
            "destination_ip": self.destination_ip,
            "destination_port": self.destination_port,
            "protocol": self.protocol,
            "classification": self.classification,
            "type": self.classification,
            "probability": self.probability,
            "confidence": round(float(self.probability or 0.0) * 100, 1),
            "risk_label": self.risk_label,
            "severity": severity_for(self.risk_label),
            "risk_score": self.risk_score,
            "rationale": self.rationale,
            "explanation": explanation,
            "model_version": self.model_version,
            "model_dataset": self.model_dataset,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(Base):
    """Append-only audit trail of privileged platform actions."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_ts", "ts"),
        Index("ix_audit_logs_actor", "actor"),
        Index("ix_audit_logs_action", "action"),
    )

    # ``BIGSERIAL``-equivalent on Postgres; SQLite (used in the pytest
    # harness) doesn't autoincrement BIGINT primary keys, so we fall back
    # to a plain ``INTEGER PRIMARY KEY`` for the test variant.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(sqlite.INTEGER(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        nullable=False,
    )
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat() if self.ts else None,
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "payload": dict(self.payload or {}),
        }
