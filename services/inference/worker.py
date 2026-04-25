from __future__ import annotations

import json
import logging

import redis

from services.api.app import create_app
from services.api.extensions import db
from services.api.models import AttackLog
from shared.config import get_settings
from shared.logging_utils import configure_logging
from shared.schemas import FlowFeatureEvent

from .service import InferenceService

logger = logging.getLogger(__name__)


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    inference_service = InferenceService()
    app = create_app()

    with app.app_context():
        while True:
            raw = redis_client.blpop(settings.inference_queue, timeout=5)
            if not raw:
                continue
            _, payload = raw
            try:
                flow_event = FlowFeatureEvent(**json.loads(payload))
                result = inference_service.classify_flow(
                    flow_id=flow_event.flow_id,
                    features=flow_event.features,
                    context=flow_event.context,
                )
                record = AttackLog(
                    flow_id=result.flow_id,
                    source_ip=str(flow_event.context.get("src_ip", "")),
                    source_port=int(flow_event.context.get("src_port", 0)),
                    destination_ip=str(flow_event.context.get("dst_ip", "")),
                    destination_port=int(flow_event.context.get("dst_port", 0)),
                    protocol=str(flow_event.context.get("protocol", "")),
                    classification=result.classification,
                    probability=result.probability,
                    risk_label=result.risk_label,
                    risk_score=result.risk_score,
                    rationale=result.rationale,
                )
                db.session.add(record)
                db.session.commit()
            except Exception as exc:
                # Keep worker alive and avoid broken transaction state.
                db.session.rollback()
                logger.exception("inference_worker_failed error=%s", exc)


if __name__ == "__main__":
    run()

