"""Lightweight dependency providers used by route handlers.

The broker is process-cached (one connection pool per Gunicorn worker). Tests
can swap the cached instance via :func:`set_broker`.
"""

from __future__ import annotations

from shared.broker import Broker, RedisStreamsBroker

_broker: Broker | None = None


def get_broker() -> Broker:
    global _broker
    if _broker is None:
        _broker = RedisStreamsBroker()
    return _broker


def set_broker(broker: Broker | None) -> None:
    """Test helper. Pass ``None`` to reset the cache."""

    global _broker
    _broker = broker
