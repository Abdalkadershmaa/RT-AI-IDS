"""Schemas for asynchronous prediction jobs (HTTP-initiated)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass
class PredictJob:
    """Work item enqueued by the API and consumed by the inference worker.

    ``traceparent`` carries W3C trace-context for distributed tracing so the
    inference worker can continue the span tree started by the HTTP request.
    Optional — empty string when tracing is disabled.
    """

    job_id: str
    flow_id: str
    features: list[float]
    context: dict[str, Any]
    submitted_at: str = field(default_factory=_utcnow_iso)
    traceparent: str = ""
    tracestate: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PredictJobResult:
    """Cached result of a prediction job, returned by the polling endpoint."""

    job_id: str
    status: str  # "pending" | "completed" | "failed"
    flow_id: str | None = None
    classification: str | None = None
    probability: float | None = None
    risk_label: str | None = None
    risk_score: float | None = None
    rationale: list[str] = field(default_factory=list)
    alert_id: int | None = None
    model_version: str | None = None
    model_dataset: str | None = None
    error: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
