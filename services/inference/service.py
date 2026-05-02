from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shared.schemas import DetectionResult

from .model_service import ModelService
from .wireless_rules import evaluate_wireless_findings
from .xai import submit_lime_explanation


def _risk_label(score: float) -> str:
    if score > 0.8:
        return "very_high"
    if score > 0.6:
        return "high"
    if score > 0.4:
        return "medium"
    if score > 0.2:
        return "low"
    return "minimal"


class InferenceService:
    def __init__(self, model_service: ModelService | None = None) -> None:
        self.model_service = model_service or ModelService()

    def classify_flow(
        self, flow_id: str, features: list[float], context: dict[str, Any]
    ) -> DetectionResult:
        classification, probability, risk_score = self.model_service.predict(features)
        rationale = evaluate_wireless_findings(context.get("wireless", {}))
        if classification != "Benign" and "ml_model_flagged_flow" not in rationale:
            rationale.append("ml_model_flagged_flow")
        result = DetectionResult(
            flow_id=flow_id,
            classification=classification,
            probability=probability,
            risk_label=_risk_label(risk_score),
            risk_score=risk_score,
            rationale=rationale,
            observed_at=datetime.now(tz=UTC).isoformat(),
        )
        if classification != "Benign":
            models = self.model_service.load()
            submit_lime_explanation(models.explainer, models.classifier, features, flow_id)
        return result
