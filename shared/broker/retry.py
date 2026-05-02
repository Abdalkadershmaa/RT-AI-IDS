"""Retry-with-DLQ helper for broker consumers.

Workers wrap their per-message handler in :func:`process_with_retries`. On
exception the handler is retried in-process up to ``max_retries`` times with
exponential backoff. After the budget is exhausted the message is published
to ``<original_stream>_dlq`` and acknowledged so the consumer-group head
advances. Successful handlers are acked exactly once.

This intentionally lives in shared/ so flow_builder, inference, and any
future worker share the same retry semantics.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .base import BrokerMessage
from .redis_streams import RedisStreamsBroker

logger = logging.getLogger(__name__)


def process_with_retries(
    broker: RedisStreamsBroker,
    message: BrokerMessage,
    handler: Callable[[BrokerMessage], None],
    *,
    max_retries: int,
    backoff_base_seconds: float = 0.5,
    backoff_cap_seconds: float = 5.0,
) -> bool:
    """Run ``handler(message)`` with retries; route to DLQ on persistent failure.

    Returns ``True`` if the handler succeeded, ``False`` if the message was
    DLQ'd. The message is acked in either terminal state. ``max_retries`` is
    the *total* number of attempts, not retries-after-first; ``max_retries=1``
    means "no retry" and ``max_retries=3`` means "try 3 times".
    """

    max_retries = max(max_retries, 1)

    last_exc: BaseException | None = None
    for attempt in range(1, max_retries + 1):
        try:
            handler(message)
            broker.ack(message.stream, message.message_id)
            return True
        except Exception as exc:
            last_exc = exc
            logger.exception(
                "broker_handler_failed stream=%s id=%s attempt=%d/%d",
                message.stream,
                message.message_id,
                attempt,
                max_retries,
            )
            if attempt < max_retries:
                delay = min(backoff_base_seconds * (2 ** (attempt - 1)), backoff_cap_seconds)
                time.sleep(delay)

    # Exhausted retries — route to DLQ and ack to unblock the group head.
    broker.publish_dlq(
        original_stream=message.stream,
        message_id=message.message_id,
        payload=message.payload,
        error=str(last_exc) if last_exc else "unknown_error",
        attempts=max_retries,
    )
    broker.ack(message.stream, message.message_id)
    logger.error(
        "broker_message_routed_to_dlq stream=%s id=%s attempts=%d",
        message.stream,
        message.message_id,
        max_retries,
    )
    return False
