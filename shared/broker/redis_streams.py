"""Redis Streams implementation of :class:`Broker`.

Each logical queue is a single Redis stream consumed by a named consumer
group. New messages are stored as a JSON blob under the field ``data``. The
group is created lazily and idempotently on the first ``consume`` call.

Per-job results (used by the async ``/predict`` endpoint) are stored as
plain Redis keys with a TTL so the API can poll them with O(1) latency
without touching the relational database.

Streams are trimmed approximately at publish time using ``MAXLEN ~ N`` so a
backlogged or paused consumer cannot cause unbounded Redis memory growth.
The cap is configurable via ``BROKER_MAX_STREAM_LEN`` (default 100 000) and
applies to every ``publish`` call unless explicitly overridden.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

import redis
from redis.exceptions import ResponseError

from shared.config import get_settings

from .base import Broker, BrokerMessage

logger = logging.getLogger(__name__)


class RedisStreamsBroker(Broker):
    """Concrete broker backed by Redis Streams + consumer groups."""

    def __init__(
        self,
        url: str | None = None,
        group: str | None = None,
        default_maxlen: int | None = None,
    ) -> None:
        settings = get_settings()
        self._url = url or settings.redis_url
        self._group = group or settings.consumer_group
        self._default_maxlen = (
            default_maxlen if default_maxlen is not None else settings.broker_max_stream_len
        )
        self._client: redis.Redis = redis.Redis.from_url(
            self._url, decode_responses=True, socket_timeout=10, socket_connect_timeout=5
        )
        self._known_groups: set[str] = set()

    @property
    def client(self) -> redis.Redis:
        return self._client

    def publish(
        self,
        stream: str,
        payload: dict[str, Any],
        maxlen: int | None = None,
    ) -> str:
        """Append a message to ``stream`` and return its assigned id.

        Streams are approximately trimmed to ``maxlen`` (or the broker default)
        to bound Redis memory under sustained load. Pass ``maxlen=0`` to
        publish without any trim (useful for one-off DLQ writes).
        """

        cap = self._default_maxlen if maxlen is None else maxlen
        kwargs: dict[str, Any] = {}
        if cap and cap > 0:
            kwargs["maxlen"] = cap
            kwargs["approximate"] = True
        return self._client.xadd(stream, {"data": json.dumps(payload)}, **kwargs)

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
        should_stop: Callable[[], bool] | None = None,
    ) -> Iterator[BrokerMessage]:
        """Yield messages from ``streams`` until the caller breaks the loop.

        ``should_stop`` is polled between blocking reads so workers can react
        to SIGTERM without waiting for the full ``block_ms`` window.
        """

        for stream in streams:
            self._ensure_group(stream)

        stream_keys = {stream: ">" for stream in streams}
        while True:
            if should_stop is not None and should_stop():
                return
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

    def publish_dlq(
        self,
        original_stream: str,
        message_id: str,
        payload: dict[str, Any],
        error: str,
        attempts: int,
    ) -> str:
        """Publish a poison message to ``<original_stream>_dlq`` for ops review.

        The DLQ stream is bounded the same way as live streams. Failures here
        are logged but not raised — losing the DLQ write must not crash the
        worker that is already handling a failure.
        """

        from datetime import UTC, datetime

        dlq_stream = f"{original_stream}_dlq"
        envelope = {
            "original_stream": original_stream,
            "original_message_id": message_id,
            "original_payload": payload,
            "error": error,
            "attempts": attempts,
            "failed_at": datetime.now(tz=UTC).isoformat(),
        }
        try:
            return self.publish(dlq_stream, envelope)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "broker_dlq_publish_failed stream=%s id=%s error=%s",
                dlq_stream,
                message_id,
                exc,
            )
            return ""

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
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("redis_streams_close_failed error=%s", exc)
