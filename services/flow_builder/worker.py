"""Flow-builder worker.

Consumes ``packet_ingest`` from the broker, threads packets through a
:class:`FlowBuilderService`, and republishes any terminated flows onto
``flow_inference`` for the inference worker.
"""

from __future__ import annotations

import logging
import os
import socket

from shared.broker import RedisStreamsBroker
from shared.config import get_settings
from shared.observability import bind_correlation_id, configure_logging
from shared.schemas import PacketEvent

from .service import FlowBuilderService

logger = logging.getLogger(__name__)


def _consumer_name() -> str:
    return f"flow-builder-{socket.gethostname()}-{os.getpid()}"


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    broker = RedisStreamsBroker()
    flow_builder = FlowBuilderService()
    consumer = _consumer_name()
    logger.info("flow_builder_starting consumer=%s stream=%s", consumer, settings.ingest_stream)

    for message in broker.consume(streams=[settings.ingest_stream], consumer=consumer):
        try:
            bind_correlation_id(message.message_id)
            packet = PacketEvent(**message.payload)
            flow_events = flow_builder.process_packet(packet)
            for flow_event in flow_events:
                broker.publish(settings.flow_inference_stream, flow_event.to_dict())
        except Exception:
            logger.exception(
                "flow_builder_message_failed stream=%s id=%s",
                message.stream,
                message.message_id,
            )
        finally:
            broker.ack(message.stream, message.message_id)


if __name__ == "__main__":
    run()
