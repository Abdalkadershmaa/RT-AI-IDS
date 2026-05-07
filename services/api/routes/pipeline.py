"""End-to-end pipeline health probe.

``GET /api/v1/health/pipeline`` is a JWT-protected synthetic test that
confirms the **whole** alert delivery path works: API publishes a benign
predict-job, the inference worker picks it up, runs the model, persists
an alert, and caches the result back on Redis. The probe polls the result
key with a short timeout and reports each stage's status.

Use cases:
* External uptime monitor (Pingdom / Datadog Synthetic) that needs to fail
  loudly when alerts stop being produced — not just when ``/ready`` lies.
* Kubernetes startup-probe gate before flipping a deploy live.
* Manual debugging during incidents.

This is **not** the Kubernetes liveness probe — that's ``/health``. This is
**not** the readiness probe — that's ``/ready`` (DB connectivity only).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from shared.config import get_settings
from shared.observability.metrics import (
    pipeline_probe_latency_seconds,
    pipeline_probe_status,
)
from shared.schemas import PredictJob

from ..deps import get_broker

logger = logging.getLogger(__name__)
pipeline_bp = Blueprint("pipeline", __name__, url_prefix="/api/v1")


# A 39-element zero vector is the contract the inference service expects
# for the autoencoder; sending zeros guarantees a stable, deterministic
# classification for the probe and never produces a HIGH-severity alert.
_PROBE_FEATURES: list[float] = [0.0] * 39


@dataclass
class _PollOutcome:
    """Result of polling the broker cache for the probe's job_id."""

    result: dict[str, Any] | None
    corrupt: bool
    poll_latency_ms: float


def _result_key(job_id: str) -> str:
    return f"predict_results:{job_id}"


def _stage(name: str, status: str, *, latency_ms: float | None = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": status}
    if latency_ms is not None:
        payload["latency_ms"] = round(latency_ms, 2)
    payload.update(extra)
    return payload


def _emit_gauges(status: str, total_latency_ms: float) -> None:
    """Mirror probe outcome into the Prometheus gauges."""

    gauge_value = {"ok": 1.0, "degraded": 0.5, "down": 0.0}.get(status, 0.0)
    pipeline_probe_status.set(gauge_value)
    pipeline_probe_latency_seconds.set(total_latency_ms / 1000.0)


def _build_response(
    overall_status: str,
    stages: list[dict[str, Any]],
    *,
    job_id: str,
    overall_start: float,
    extra: dict[str, Any] | None = None,
) -> tuple:
    latency_ms = (time.perf_counter() - overall_start) * 1000.0
    _emit_gauges(overall_status, latency_ms)
    body: dict[str, Any] = {
        "status": overall_status,
        "stages": stages,
        "latency_ms": round(latency_ms, 2),
        "job_id": job_id,
    }
    if extra:
        body.update(extra)
    http_status = 200 if overall_status == "ok" else 503
    return jsonify(body), http_status


def _poll_for_result(broker: Any, job_id: str, deadline: float) -> _PollOutcome:
    """Poll the result cache until the worker writes a terminal status."""

    poll_start = time.perf_counter()
    while time.monotonic() < deadline:
        stored = broker.load_result(_result_key(job_id))
        if stored.corrupt:
            return _PollOutcome(
                result=None,
                corrupt=True,
                poll_latency_ms=(time.perf_counter() - poll_start) * 1000.0,
            )
        candidate = stored.payload
        # The API pre-caches a "pending" placeholder before publishing; only
        # accept the worker's "completed" / "failed" terminal write.
        if candidate is not None and candidate.get("status") in {"completed", "failed"}:
            return _PollOutcome(
                result=candidate,
                corrupt=False,
                poll_latency_ms=(time.perf_counter() - poll_start) * 1000.0,
            )
        time.sleep(0.05)
    return _PollOutcome(
        result=None,
        corrupt=False,
        poll_latency_ms=(time.perf_counter() - poll_start) * 1000.0,
    )


@pipeline_bp.get("/health/pipeline")
@jwt_required()
def pipeline_probe() -> tuple:
    """Run a synthetic predict-job through the full pipeline."""

    settings = get_settings()
    timeout_seconds = settings.pipeline_probe_timeout_seconds
    deadline = time.monotonic() + timeout_seconds

    job_id = f"probe-{uuid.uuid4().hex[:12]}"
    stages: list[dict[str, Any]] = []
    overall_start = time.perf_counter()

    # Stage 1: enqueue.
    enqueue_start = time.perf_counter()
    try:
        broker = get_broker()
        job = PredictJob(
            job_id=job_id,
            flow_id=job_id,
            features=list(_PROBE_FEATURES),
            context={"source": "pipeline_probe", "synthetic": True},
        )
        broker.publish(settings.predict_jobs_stream, job.to_dict())
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("pipeline_probe_publish_failed job_id=%s", job_id)
        stages.append(_stage("publish", "down", error=str(exc)))
        return _build_response("down", stages, job_id=job_id, overall_start=overall_start)
    publish_latency = (time.perf_counter() - enqueue_start) * 1000.0
    stages.append(_stage("publish", "ok", latency_ms=publish_latency))

    # Stage 2: poll the result key until the worker writes it or the budget elapses.
    outcome = _poll_for_result(broker, job_id, deadline)
    if outcome.corrupt:
        stages.append(_stage("inference", "down", error="cached result corrupt"))
        return _build_response("down", stages, job_id=job_id, overall_start=overall_start)
    if outcome.result is None:
        stages.append(
            _stage(
                "inference",
                "degraded",
                latency_ms=outcome.poll_latency_ms,
                error=f"no result within {timeout_seconds}s",
            )
        )
        logger.warning(
            "pipeline_probe_timeout",
            extra={"job_id": job_id, "timeout_s": timeout_seconds},
        )
        return _build_response("degraded", stages, job_id=job_id, overall_start=overall_start)

    stages.append(_stage("inference", "ok", latency_ms=outcome.poll_latency_ms))
    result = outcome.result

    # Stage 3: confirm the worker reported success and recorded an alert id.
    job_status = result.get("status")
    alert_id = result.get("alert_id")
    if job_status != "completed":
        stages.append(_stage("worker", "down", error=str(result.get("error") or job_status)))
        overall_status = "down"
    elif alert_id is None:
        stages.append(_stage("persist", "degraded", error="alert_id missing"))
        overall_status = "degraded"
    else:
        stages.append(_stage("worker", "ok", classification=result.get("classification")))
        stages.append(_stage("persist", "ok", alert_id=alert_id))
        overall_status = "ok"

    extra = {
        "model_version": result.get("model_version"),
        "model_dataset": result.get("model_dataset"),
    }
    logger.info(
        "pipeline_probe_completed",
        extra={"job_id": job_id, "status": overall_status, "alert_id": alert_id},
    )
    return _build_response(overall_status, stages, job_id=job_id, overall_start=overall_start, extra=extra)
