"""Async Redis Streams publisher.

Uses :mod:`redis.asyncio` so the event loop is never blocked on a thread-pool
hop. The publisher exposes a ``dropped`` counter so the ingestion service can
log/expose how many packets the bounded capture queue had to discard under
load.
"""

from __future__ import annotations

import json
import logging

from redis import asyncio as aioredis

from shared.config import get_settings
from shared.schemas import PacketEvent

logger = logging.getLogger(__name__)


class RedisPublisher:
    """Append :class:`PacketEvent` records to the ingest stream."""

    def __init__(self, dropped_counter: int = 0) -> None:
        settings = get_settings()
        self._stream = settings.ingest_stream
        self._client: aioredis.Redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=5,
        )
        self.dropped = dropped_counter

    async def publish(self, packet: PacketEvent) -> None:
        await self._client.xadd(self._stream, {"data": json.dumps(packet.to_dict())})

    def record_drop(self, count: int = 1) -> None:
        self.dropped += count

    async def close(self) -> None:
        try:
            await self._client.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("ingestion_publisher_close_failed error=%s", exc)
