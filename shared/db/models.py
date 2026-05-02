"""ORM models. Framework-agnostic — usable from any service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base used by every ORM model in the project."""


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
        """Render an alert as a JSON-serializable dict for API responses."""

        return {
            "id": self.id,
            "flow_id": self.flow_id,
            "source_ip": self.source_ip,
            "source_port": self.source_port,
            "destination_ip": self.destination_ip,
            "destination_port": self.destination_port,
            "protocol": self.protocol,
            "classification": self.classification,
            "probability": self.probability,
            "risk_label": self.risk_label,
            "risk_score": self.risk_score,
            "rationale": self.rationale,
            "model_version": self.model_version,
            "model_dataset": self.model_dataset,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
