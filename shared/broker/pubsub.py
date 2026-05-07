"""Redis pub/sub helpers used for fan-out of newly persisted alerts.

Server-Sent Events used to poll the database every ~1 s (1000 SSE
clients = 1000 qps just for the live feed). With pub/sub the inference
worker publishes a tiny payload to one Redis channel after each insert
and every connected SSE handler receives it within milliseconds — DB
load drops by ~99 % and observed end-to-end alert latency drops below
500 ms.

The publisher is intentionally never on the hot path: a transient Redis
error logs a warning and returns 0 so the alert stays persisted in
Postgres, and the SSE poller's ``since_id`` cursor recovery picks the
miss up on the next reconnect. Pub/sub here is a *latency optimisation*,
not a durability guarantee.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from typing import Any

import redis
from redis.exceptions import RedisError

from shared.config import get_settings

logger = logging.getLogger(__name__)

# Default channel for fanned-out alert notifications. Override via env var
# in production deployments that multiplex multiple tenants on one Redis.
ALERTS_CHANNEL = os.getenv("ALERTS_PUBSUB_CHANNEL", "alerts:new")

_publisher_client: redis.Redis | None = None


def _publisher() -> redis.Redis:
    global _publisher_client
    if _publisher_client is None:
        settings = get_settings()
        _publisher_client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
    return _publisher_client


def publish_alert(payload: dict[str, Any], channel: str = ALERTS_CHANNEL) -> int:
    """Publish ``payload`` on ``channel``. Returns subscriber count, or 0 on failure."""

    try:
        return int(_publisher().publish(channel, json.dumps(payload)))
    except RedisError as exc:
        logger.warning("alert_pubsub_publish_failed channel=%s error=%s", channel, exc)
        return 0


def listen_alerts(
    *,
    channel: str = ALERTS_CHANNEL,
    timeout_seconds: float = 1.0,
) -> Iterator[dict[str, Any] | None]:
    """Yield alert payloads as they arrive on ``channel``.

    Yields ``None`` whenever ``timeout_seconds`` elapses with no message,
    so the SSE handler can flush a heartbeat and check its shutdown flag
    without blocking forever. Closes cleanly when the consumer breaks
    out of the iterator (Python's generator finalisation reclaims the
    Redis connection).
    """

    settings = get_settings()
    client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=max(timeout_seconds + 1.0, 5.0),
        socket_connect_timeout=3,
    )
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    try:
        pubsub.subscribe(channel)
        while True:
            message = pubsub.get_message(timeout=timeout_seconds)
            if message is None:
                yield None
                continue
            data = message.get("data")
            if not data:
                yield None
                continue
            try:
                payload = json.loads(data)
            except (TypeError, ValueError):
                logger.warning("alert_pubsub_invalid_json channel=%s data=%r", channel, data)
                continue
            if not isinstance(payload, dict):
                continue
            yield payload
    finally:
        try:
            pubsub.close()
        except RedisError:
            pass
        try:
            client.close()
        except RedisError:
            pass


__all__ = ["ALERTS_CHANNEL", "listen_alerts", "publish_alert"]
