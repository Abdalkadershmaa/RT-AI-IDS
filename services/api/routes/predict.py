"""Async prediction endpoints.

``POST /api/v1/predict`` validates the input, enqueues a :class:`PredictJob`
on the broker, and returns immediately with HTTP 202 + a ``job_id``. The
inference worker picks the job up, runs the model, persists an alert, and
caches a :class:`PredictJobResult` keyed by ``job_id``.

``GET /api/v1/predict/<job_id>`` returns the cached result, or 404 when the
TTL has expired (the alert stays in the database either way).
"""

from __future__ import annotations

import logging
import uuid

from flask import Blueprint, jsonify, request, url_for
from flask_jwt_extended import jwt_required
from pydantic import ValidationError

from shared.config import get_settings
from shared.observability import bind_correlation_id
from shared.schemas import PredictJob

from ..deps import get_broker
from ..schemas.predict import (
    PredictAcceptedResponse,
    PredictRequest,
    PredictResultResponse,
)

logger = logging.getLogger(__name__)
predict_bp = Blueprint("predict", __name__, url_prefix="/api/v1")


def _result_key(job_id: str) -> str:
    return f"predict_results:{job_id}"


def _serialize_validation(exc: ValidationError) -> list[dict[str, str]]:
    """Render a pydantic validation error as JSON-safe primitives."""

    return [
        {"loc": ".".join(str(part) for part in err.get("loc", ())), "msg": err.get("msg", "")}
        for err in exc.errors(include_url=False, include_input=False)
    ]


@predict_bp.post("/predict")
@jwt_required()
def predict() -> tuple:
    """Enqueue a prediction job. Returns 202 + ``job_id``."""

    try:
        body = PredictRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return (
            jsonify({"error": "invalid_request", "detail": _serialize_validation(exc)}),
            400,
        )

    job_id = uuid.uuid4().hex
    flow_id = body.flow_id or job_id
    bind_correlation_id(job_id)

    job = PredictJob(
        job_id=job_id,
        flow_id=flow_id,
        features=body.features,
        context=body.context,
    )

    settings = get_settings()
    broker = get_broker()
    broker.publish(settings.predict_jobs_stream, job.to_dict())

    poll_url = url_for("predict.predict_result", job_id=job_id)
    response = PredictAcceptedResponse(
        job_id=job_id,
        status="pending",
        poll_url=poll_url,
    )
    logger.info("predict_job_enqueued", extra={"job_id": job_id, "flow_id": flow_id})
    return jsonify(response.model_dump()), 202


@predict_bp.get("/predict/<job_id>")
@jwt_required()
def predict_result(job_id: str) -> tuple:
    """Return the cached result for ``job_id`` (404 if expired)."""

    bind_correlation_id(job_id)
    broker = get_broker()
    result = broker.load_result(_result_key(job_id))
    if result is None:
        return jsonify({"error": "not_found", "detail": "job_id unknown or expired"}), 404
    response = PredictResultResponse.model_validate(result)
    return jsonify(response.model_dump()), 200
