"""Flow-builder worker.

Consumes ``packet_ingest`` from the broker, threads packets through a
:class:`FlowBuilderService`, and republishes any terminated flows onto
``flow_inference`` for the inference worker.

Persistent failures are retried in-process and ultimately routed to
``packet_ingest_dlq``. Shutdown is signal-driven so the consumer exits
cleanly on ``docker compose down``.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
from typing import Any

from shared.broker import BrokerMessage, RedisStreamsBroker, process_with_retries
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

    shutdown = _install_signal_handlers("flow_builder")

    def _dispatch(message: BrokerMessage) -> None:
        bind_correlation_id(message.message_id)
        packet = PacketEvent(**message.payload)
        flow_events = flow_builder.process_packet(packet)
        for flow_event in flow_events:
            broker.publish(settings.flow_inference_stream, flow_event.to_dict())

    for message in broker.consume(
        streams=[settings.ingest_stream],
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

    logger.info("flow_builder_stopped consumer=%s", consumer)


def _install_signal_handlers(component: str) -> dict[str, bool]:
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
