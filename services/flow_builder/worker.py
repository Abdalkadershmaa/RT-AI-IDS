from __future__ import annotations

import json
import logging
import redis

from shared.config import get_settings
from shared.logging_utils import configure_logging
from shared.schemas import PacketEvent

from .service import FlowBuilderService

logger = logging.getLogger(__name__)


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    flow_builder = FlowBuilderService()

    while True:
        raw = client.blpop(settings.ingest_queue, timeout=5)
        if not raw:
            continue
        _, payload = raw
        try:
            packet = PacketEvent(**json.loads(payload))
            flow_events = flow_builder.process_packet(packet)
            for flow_event in flow_events:
                client.rpush(settings.inference_queue, json.dumps(flow_event.to_dict()))
        except Exception as exc:
            # Keep queue consumption alive when malformed records appear.
            logger.warning("failed_to_process_packet_event error=%s", exc)
            continue


if __name__ == "__main__":
    run()

