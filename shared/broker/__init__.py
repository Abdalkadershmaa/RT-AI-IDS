"""Pluggable broker abstraction.

Today we ship :class:`RedisStreamsBroker`. The :class:`Broker` ABC keeps the
door open for swapping in NATS/RabbitMQ/Celery in the future without touching
producers or consumers.
"""

from .base import Broker, BrokerMessage
from .redis_streams import RedisStreamsBroker
from .retry import process_with_retries

__all__ = ["Broker", "BrokerMessage", "RedisStreamsBroker", "process_with_retries"]
