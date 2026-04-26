"""Redis Streams implementation of :class:`Broker`.

Each logical queue is a single Redis stream consumed by a named consumer
group. New messages are stored as a JSON blob under the field ``data``. The
group is created lazily and idempotently on the first ``consume`` call.

Per-job results (used by the async ``/predict`` endpoint) are stored as
plain Redis keys with a TTL so the API can poll them with O(1) latency
without touching the relational database.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import redis
from redis.exceptions import ResponseError

from shared.config import get_settings

from .base import Broker, BrokerMessage

logger = logging.getLogger(__name__)


class RedisStreamsBroker(Broker):
    """Concrete broker backed by Redis Streams + consumer groups."""

    def __init__(self, url: str | None = None, group: str | None = None) -> None:
        settings = get_settings()
        self._url = url or settings.redis_url
        self._group = group or settings.consumer_group
        self._client: redis.Redis = redis.Redis.from_url(
            self._url, decode_responses=True, socket_timeout=10, socket_connect_timeout=5
        )
        self._known_groups: set[str] = set()

    @property
    def client(self) -> redis.Redis:
        return self._client

    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        """Append a message to ``stream`` and return its assigned id."""

        return self._client.xadd(stream, {"data": json.dumps(payload)})

    def _ensure_group(self, stream: str) -> None:
        """Create the consumer group on ``stream`` if it doesn't exist."""

        key = f"{stream}::{self._group}"
        if key in self._known_groups:
            return
        try:
            self._client.xgroup_create(stream, self._group, id="$", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._known_groups.add(key)

    def consume(
        self,
        streams: list[str],
        consumer: str,
        block_ms: int = 5_000,
        count: int = 64,
    ) -> Iterator[BrokerMessage]:
        """Yield messages from ``streams`` until the caller breaks the loop."""

        for stream in streams:
            self._ensure_group(stream)

        stream_keys = {stream: ">" for stream in streams}
        while True:
            response = self._client.xreadgroup(
                groupname=self._group,
                consumername=consumer,
                streams=stream_keys,
                count=count,
                block=block_ms,
            )
            if not response:
                continue
            for stream_name, entries in response:
                for message_id, fields in entries:
                    raw = fields.get("data")
                    if raw is None:
                        # Malformed message — ack and drop so the group head advances.
                        self.ack(stream_name, message_id)
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning(
                            "broker_drop_unparseable_message stream=%s id=%s",
                            stream_name,
                            message_id,
                        )
                        self.ack(stream_name, message_id)
                        continue
                    yield BrokerMessage(stream=stream_name, message_id=message_id, payload=payload)

    def ack(self, stream: str, message_id: str) -> None:
        self._client.xack(stream, self._group, message_id)

    def store_result(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._client.set(key, json.dumps(value), ex=max(ttl_seconds, 1))

    def load_result(self, key: str) -> dict[str, Any] | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover - defensive
            pass
