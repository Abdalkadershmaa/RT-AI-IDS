from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

FEATURE_COUNT = 39


class PredictRequest(BaseModel):
    """Body of ``POST /api/v1/predict``."""

    model_config = ConfigDict(extra="forbid")

    flow_id: str | None = Field(default=None, max_length=128)
    features: list[float] = Field(min_length=FEATURE_COUNT, max_length=FEATURE_COUNT)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("features")
    @classmethod
    def _no_nan_or_inf(cls, value: list[float]) -> list[float]:
        for entry in value:
            if math.isnan(entry) or math.isinf(entry):
                raise ValueError("features must be finite numeric values (no NaN/inf)")
        return value


class PredictAcceptedResponse(BaseModel):
    """Returned with HTTP 202 when a prediction is enqueued."""

    job_id: str
    status: str = "pending"
    poll_url: str


class PredictResultResponse(BaseModel):
    """Returned by ``GET /api/v1/predict/<job_id>``."""

    # ``model_version`` / ``model_dataset`` collide with Pydantic v2's
    # ``model_`` reserved namespace; opt out so the public field names match
    # the OpenAPI schema and Flutter / TypeScript clients.
    model_config = ConfigDict(protected_namespaces=())

    job_id: str
    status: str
    flow_id: str | None = None
    classification: str | None = None
    probability: float | None = None
    risk_label: str | None = None
    risk_score: float | None = None
    rationale: list[str] = Field(default_factory=list)
    explanation: list[dict[str, Any]] = Field(default_factory=list)
    alert_id: int | None = None
    model_version: str | None = None
    model_dataset: str | None = None
    error: str | None = None
    completed_at: str | None = None

    @property
    def severity(self) -> str | None:
        # Convenience: clients can read either ``risk_label`` (lowercase
        # tier) or ``severity`` (uppercase) — provided through
        # ``model_dump()`` as an additional field below.
        if self.risk_label is None:
            return None
        from shared.db.models import severity_for

        return severity_for(self.risk_label)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        data = super().model_dump(*args, **kwargs)
        if self.risk_label is not None:
            data["severity"] = self.severity
        if self.classification is not None:
            data["type"] = self.classification
        if self.probability is not None:
            data["confidence"] = round(float(self.probability) * 100, 1)
        return data
