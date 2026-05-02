"""Redis-backed JWT denylist for logout / revocation."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import redis
from redis.exceptions import RedisError

from shared.config import get_settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=3,
        )
    return _client


def denylist_key(jti: str) -> str:
    return f"jwt_denylist:{jti}"


def revoke_token(jti: str, expires_at: datetime) -> None:
    ttl = max(int((expires_at - datetime.now(tz=UTC)).total_seconds()), 1)
    get_client().set(denylist_key(jti), "1", ex=ttl)


def is_token_revoked(jti: str) -> bool:
    try:
        return get_client().get(denylist_key(jti)) is not None
    except RedisError as exc:
        logger.warning("jwt_denylist_lookup_failed error=%s", exc)
        return True
