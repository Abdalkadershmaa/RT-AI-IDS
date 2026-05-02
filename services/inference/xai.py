"""Background LIME explanation helpers."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lime-xai")


def submit_lime_explanation(
    explainer: Any,
    classifier: Any,
    features: list[float],
    flow_id: str,
) -> None:
    """Queue a best-effort LIME explanation without blocking inference."""

    if explainer is None:
        return
    _executor.submit(_run_lime_explanation, explainer, classifier, features, flow_id)


def _run_lime_explanation(
    explainer: Any,
    classifier: Any,
    features: list[float],
    flow_id: str,
) -> None:
    try:
        row = np.array(features, dtype=float)
        explanation = explainer.explain_instance(  # type: ignore[attr-defined]
            row,
            classifier.predict_proba,
            num_features=min(len(features), 10),
        )
        if hasattr(explanation, "as_list"):
            rationale = [str(item[0]) for item in explanation.as_list()]
        else:
            rationale = [str(explanation)]
        logger.info("lime_explanation_ready", extra={"flow_id": flow_id, "rationale": rationale})
    except Exception as exc:  # noqa: BLE001 - background best-effort enrichment
        logger.warning("lime_explanation_failed flow_id=%s error=%s", flow_id, exc)
