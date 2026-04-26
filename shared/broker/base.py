"""Broker abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


@dataclass
class BrokerMessage:
    """A message handed to a consumer.

    Consumers must call :meth:`Broker.ack` with ``message_id`` after processing
    in order for the broker to drop the message from the in-flight set.
    """

    stream: str
    message_id: str
    payload: dict[str, Any]


class Broker(ABC):
    """Minimal interface every broker implementation must support."""

    @abstractmethod
    def publish(self, stream: str, payload: dict[str, Any]) -> str: ...

    @abstractmethod
    def consume(
        self,
        streams: list[str],
        consumer: str,
        block_ms: int = 5_000,
        count: int = 64,
    ) -> Iterator[BrokerMessage]: ...

    @abstractmethod
    def ack(self, stream: str, message_id: str) -> None: ...

    @abstractmethod
    def store_result(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None: ...

    @abstractmethod
    def load_result(self, key: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def close(self) -> None: ...
