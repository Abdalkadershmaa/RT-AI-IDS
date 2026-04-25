from __future__ import annotations

import asyncio
import json

import redis

from shared.config import get_settings
from shared.schemas import PacketEvent


class RedisPublisher:
    def __init__(self) -> None:
        settings = get_settings()
        self._queue = settings.ingest_queue
        self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    async def publish(self, packet: PacketEvent) -> None:
        await asyncio.to_thread(self._client.rpush, self._queue, json.dumps(packet.to_dict()))

