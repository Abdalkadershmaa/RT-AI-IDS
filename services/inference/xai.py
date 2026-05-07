"""LIME explanation helper.

The explainer runs in a small thread pool so the synchronous LIME work does
not block the inference event loop or hot-path. Every request returns
within :data:`LIME_BUDGET_SECONDS` — exceeding that budget yields an empty
attribution list rather than slowing down the alert pipeline.

The result format is the additive shape that the API, frontend, and
Chrome extension all consume:

    [
        {"feature": "syn_flag_count", "weight": 0.42},
        {"feature": "packet_rate", "weight": 0.31},
        ...
    ]
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Hard cap on LIME wall-clock per alert. Above this budget the alert is
# served with ``explanation=[]`` and the explainer is left to finish in the
# background; the result is logged but does not block persistence. 250 ms
# keeps p99 alert latency under the 1 s SSE-fanout SLA.
LIME_BUDGET_SECONDS = 0.25

# Capped number of features rendered in a single attribution. Mirrors the
# original explainer artefact's training defaults.
LIME_MAX_FEATURES = 10

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lime-xai")


def submit_lime_explanation(
    explainer: Any,
    classifier: Any,
    features: list[float],
    flow_id: str,
    timeout: float = LIME_BUDGET_SECONDS,
) -> list[dict[str, Any]]:
    """Compute a LIME attribution for ``features``, capped at ``timeout`` seconds.

    Returns ``[]`` if:
      - the explainer artefact is not loaded;
      - the LIME run exceeds ``timeout`` (it keeps running in the
        background; only this call returns early);
      - any underlying exception is raised (logged at ``warning`` level).

    Never raises — explanation is best-effort enrichment, not a critical
    path.
    """

    if explainer is None or classifier is None:
        return []
    if not features:
        return []

    future: Future[list[dict[str, Any]]] = _executor.submit(
        _run_lime_explanation, explainer, classifier, features, flow_id
    )
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        logger.info(
            "lime_explanation_timeout",
            extra={"flow_id": flow_id, "timeout_s": timeout},
        )
        return []
    except Exception as exc:  # noqa: BLE001 - best-effort enrichment
        logger.warning("lime_explanation_failed flow_id=%s error=%s", flow_id, exc)
        return []


def _run_lime_explanation(
    explainer: Any,
    classifier: Any,
    features: list[float],
    flow_id: str,
) -> list[dict[str, Any]]:
    row = np.array(features, dtype=float)
    explanation = explainer.explain_instance(  # type: ignore[attr-defined]
        row,
        classifier.predict_proba,
        num_features=min(len(features), LIME_MAX_FEATURES),
    )
    rationale: list[dict[str, Any]] = []
    if hasattr(explanation, "as_list"):
        for item in explanation.as_list():
            try:
                feature_name, weight = item
            except (TypeError, ValueError):
                continue
            try:
                weight_f = float(weight)
            except (TypeError, ValueError):
                continue
            rationale.append({"feature": str(feature_name), "weight": weight_f})
    elif isinstance(explanation, list):
        for entry in explanation:
            if isinstance(entry, dict) and "feature" in entry and "weight" in entry:
                try:
                    rationale.append(
                        {
                            "feature": str(entry["feature"]),
                            "weight": float(entry["weight"]),
                        }
                    )
                except (TypeError, ValueError):
                    continue
    try:
        logger.info(
            "lime_explanation_ready",
            extra={"flow_id": flow_id, "feature_count": len(rationale)},
        )
    except (ValueError, OSError):
        # Best-effort: stdout/stderr may already be closed when the worker
        # thread completes after pytest tears the process logging down.
        # Swallow the error so the explanation result is still returned.
        pass
    return rationale
