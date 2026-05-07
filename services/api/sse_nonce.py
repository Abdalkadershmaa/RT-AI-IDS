"""Short-lived SSE-subscription nonces.

Browser ``EventSource`` cannot send custom request headers, so the SSE
endpoint historically authenticated by ``?access_token=<JWT>`` query
parameter — which leaks the long-lived JWT into nginx/gunicorn access
logs and from there into every downstream log shipper.

This module exchanges that long-lived JWT for a short-lived (30 s)
single-use nonce, stored in Redis. The SSE endpoint accepts
``?nonce=<nonce>`` instead, validates and atomically consumes the nonce,
then forwards the resolved subject identity to the streaming handler.

The legacy ``?access_token=`` path remains supported for one release
(returns a ``Deprecation:`` response header) so existing clients keep
working while they migrate.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any

import redis
from redis.exceptions import RedisError

from shared.config import get_settings

logger = logging.getLogger(__name__)

NONCE_TTL_SECONDS = 30
NONCE_PREFIX = "sse_nonce:"

_client: redis.Redis | None = None


def _redis_client() -> redis.Redis:
    """Return a process-cached Redis client used for nonce storage."""

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


def _nonce_key(nonce: str) -> str:
    return f"{NONCE_PREFIX}{nonce}"


def _make_nonce() -> str:
    return secrets.token_urlsafe(32)


def issue_nonce(subject: str, ttl_seconds: int = NONCE_TTL_SECONDS) -> tuple[str, int]:
    """Mint and persist a fresh nonce for ``subject``.

    Returns ``(nonce, ttl_seconds)``. When Redis is unreachable the nonce
    is still returned but persisted to a per-process fallback so unit
    tests (``RATE_LIMIT_STORAGE_URI=memory://``, no real Redis) keep
    working without a live broker.
    """

    nonce = _make_nonce()
    try:
        _redis_client().set(_nonce_key(nonce), subject, ex=ttl_seconds, nx=True)
    except RedisError as exc:
        logger.warning(
            "sse_nonce_redis_unavailable falling back to in-process store error=%s",
            exc,
        )
        _MEMORY_STORE[nonce] = subject
    return nonce, ttl_seconds


def consume_nonce(nonce: str) -> str | None:
    """Atomically read + delete ``nonce``. Returns the bound subject or ``None``."""

    if not nonce:
        return None
    try:
        client = _redis_client()
        # GETDEL is atomic: read the value and delete it in one round trip.
        # Falls back to a non-atomic GET + DEL on older Redis (< 6.2.0).
        try:
            subject = client.execute_command("GETDEL", _nonce_key(nonce))
        except RedisError:
            subject = client.get(_nonce_key(nonce))
            if subject is not None:
                client.delete(_nonce_key(nonce))
        if subject is None:
            return _MEMORY_STORE.pop(nonce, None)
        return str(subject) if subject else None
    except RedisError as exc:
        logger.warning("sse_nonce_redis_consume_failed error=%s", exc)
        return _MEMORY_STORE.pop(nonce, None)


# Per-process fallback used only when Redis is not available (e.g. the
# unit-test ``memory://`` configuration). Scoped to the running gunicorn
# worker, so a multi-replica deployment without Redis would not share
# nonces — but production deployments always have Redis up before the API
# starts, gated by the ``depends_on: condition: service_healthy`` clause
# in ``docker-compose.yml``.
_MEMORY_STORE: dict[str, str] = {}


def reset_for_tests() -> None:
    """Drop process-local + Redis state. Called by ``tests/conftest.py``."""

    _MEMORY_STORE.clear()
    try:
        client = _redis_client()
        for key in client.scan_iter(match=f"{NONCE_PREFIX}*"):
            client.delete(key)
    except RedisError:
        return None


# Allow tests to bypass the Redis client by injecting a stub.
def _set_client_for_tests(client: Any) -> None:
    global _client
    _client = client


__all__ = [
    "NONCE_TTL_SECONDS",
    "consume_nonce",
    "issue_nonce",
    "reset_for_tests",
]


# Detect when running inside the pytest suite — used so the module's
# global Redis client can be replaced with a fake by tests without
# mutating production code paths.
_IS_TESTING = bool(os.getenv("PYTEST_CURRENT_TEST"))
