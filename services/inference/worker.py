"""Inference worker.

Consumes two streams in parallel via a single consumer group:

* ``flow_inference`` — emitted by the flow builder when a flow terminates.
* ``predict_jobs``   — emitted by the API for synchronous "predict-this-vector"
  requests submitted over HTTP.

Each consumed message is classified, persisted to the database (via
:mod:`shared.db`, no Flask), and acked back to the broker. ``predict_jobs``
results are additionally cached by ``job_id`` so the API can poll them.

Failed handlers are retried in-process up to ``BROKER_MAX_RETRIES`` times
with exponential backoff. Persistent failures are routed to a per-stream
dead-letter queue (``<stream>_dlq``) so ops can inspect and replay them
without blocking the consumer-group head.

A ``SIGTERM`` (or ``SIGINT``) handler flips a stop flag that is polled
between blocking reads, so ``docker compose down`` exits cleanly within one
read window instead of being SIGKILL'd by the orchestrator.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
from typing import Any

from shared.broker import Broker, BrokerMessage, RedisStreamsBroker, process_with_retries
from shared.config import get_settings
from shared.observability import bind_correlation_id, configure_logging
from shared.schemas import DetectionResult, PredictJob, PredictJobResult

from .model_service import ModelService
from .repository import persist_alert
from .service import InferenceService

logger = logging.getLogger(__name__)


def _consumer_name() -> str:
    return f"inference-{socket.gethostname()}-{os.getpid()}"


def _result_key(job_id: str) -> str:
    return f"predict_results:{job_id}"


def _handle_predict_job(
    payload: dict[str, Any],
    inference_service: InferenceService,
    broker: Broker,
    ttl: int,
) -> None:
    job = PredictJob(**payload)
    bind_correlation_id(job.job_id)
    try:
        result = inference_service.classify_flow(
            flow_id=job.flow_id,
            features=job.features,
            context=job.context,
        )
        alert_id = persist_alert(result, job.context)
        broker.store_result(
            _result_key(job.job_id),
            PredictJobResult(
                job_id=job.job_id,
                status="completed",
                flow_id=result.flow_id,
                classification=result.classification,
                probability=result.probability,
                risk_label=result.risk_label,
                risk_score=result.risk_score,
                rationale=list(result.rationale),
                alert_id=alert_id,
                completed_at=result.observed_at,
            ).to_dict(),
            ttl_seconds=ttl,
        )
        logger.info(
            "predict_job_completed",
            extra={"job_id": job.job_id, "alert_id": alert_id, "risk_label": result.risk_label},
        )
    except Exception as exc:
        # Predict jobs surface their failure to the polling client through the
        # cached result. We intentionally swallow the exception so the message
        # is not retried + DLQ'd: a duplicate alert + duplicate result write
        # would be worse than a single failure visible to the caller.
        logger.exception("predict_job_failed job_id=%s", job.job_id)
        broker.store_result(
            _result_key(job.job_id),
            PredictJobResult(job_id=job.job_id, status="failed", error=str(exc)).to_dict(),
            ttl_seconds=ttl,
        )


def _handle_flow_event(
    payload: dict[str, Any],
    inference_service: InferenceService,
) -> DetectionResult:
    flow_id = str(payload.get("flow_id", ""))
    bind_correlation_id(flow_id or None)
    features = [float(x) for x in payload.get("features", [])]
    context = payload.get("context", {}) or {}
    result = inference_service.classify_flow(
        flow_id=flow_id,
        features=features,
        context=context,
    )
    persist_alert(result, context)
    return result


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    model_service = ModelService()
    model_service.warm_up()  # eager load — fail-fast at startup if models missing
    inference_service = InferenceService(model_service=model_service)

    broker = RedisStreamsBroker()
    streams = [settings.flow_inference_stream, settings.predict_jobs_stream]
    consumer = _consumer_name()
    logger.info("inference_worker_starting consumer=%s streams=%s", consumer, streams)

    shutdown = _install_signal_handlers("inference_worker")

    def _dispatch(message: BrokerMessage) -> None:
        if message.stream == settings.predict_jobs_stream:
            _handle_predict_job(
                message.payload,
                inference_service,
                broker,
                ttl=settings.predict_result_ttl_seconds,
            )
        else:
            _handle_flow_event(message.payload, inference_service)

    for message in broker.consume(
        streams=streams,
        consumer=consumer,
        should_stop=lambda: shutdown["requested"],
    ):
        process_with_retries(
            broker,
            message,
            _dispatch,
            max_retries=settings.broker_max_retries,
        )
        if shutdown["requested"]:
            break

    logger.info("inference_worker_stopped consumer=%s", consumer)


def _install_signal_handlers(component: str) -> dict[str, bool]:
    """Install SIGTERM/SIGINT handlers; return a flag dict the loop can poll."""

    state = {"requested": False}

    def _handler(signum: int, _frame: Any) -> None:
        if not state["requested"]:
            logger.info("%s_shutdown_requested signal=%s", component, signum)
        state["requested"] = True

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
    return state


if __name__ == "__main__":
    run()
