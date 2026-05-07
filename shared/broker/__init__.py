"""Pluggable broker abstraction.

Today we ship :class:`RedisStreamsBroker`. The :class:`Broker` ABC keeps the
door open for swapping in NATS/RabbitMQ/Celery in the future without touching
producers or consumers.
"""

from .base import Broker, BrokerMessage, JsonKeyLoad
from .pubsub import ALERTS_CHANNEL, listen_alerts, publish_alert
from .redis_streams import RedisStreamsBroker
from .retry import process_with_retries

__all__ = [
    "ALERTS_CHANNEL",
    "Broker",
    "BrokerMessage",
    "JsonKeyLoad",
    "RedisStreamsBroker",
    "listen_alerts",
    "process_with_retries",
    "publish_alert",
]
