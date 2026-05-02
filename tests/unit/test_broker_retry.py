"""Unit tests for the worker retry/DLQ helper."""

from __future__ import annotations

import pytest

fakeredis = pytest.importorskip("fakeredis")

from shared.broker import BrokerMessage, process_with_retries  # noqa: E402


def _broker():
    from shared.broker.redis_streams import RedisStreamsBroker

    fake = fakeredis.FakeRedis(decode_responses=True)
    broker = RedisStreamsBroker.__new__(RedisStreamsBroker)
    broker._url = "redis://fake"  # type: ignore[attr-defined]
    broker._group = "rt_ai_ids"  # type: ignore[attr-defined]
    broker._client = fake  # type: ignore[attr-defined]
    broker._known_groups = set()  # type: ignore[attr-defined]
    broker._default_maxlen = 0  # type: ignore[attr-defined]
    return broker, fake


def _msg(stream: str = "packet_ingest", message_id: str = "1-1") -> BrokerMessage:
    return BrokerMessage(stream=stream, message_id=message_id, payload={"k": "v"})


def test_handler_succeeds_on_first_attempt_acks_and_returns_true() -> None:
    broker, _ = _broker()
    calls: list[BrokerMessage] = []

    def _ok(message: BrokerMessage) -> None:
        calls.append(message)

    ok = process_with_retries(broker, _msg(), _ok, max_retries=3)

    assert ok is True
    assert len(calls) == 1


def test_handler_eventually_succeeds_within_retry_budget() -> None:
    broker, _ = _broker()
    attempts = {"n": 0}

    def _flaky(message: BrokerMessage) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")

    ok = process_with_retries(
        broker, _msg(), _flaky, max_retries=3, backoff_base_seconds=0.0
    )

    assert ok is True
    assert attempts["n"] == 3


def test_persistent_failure_is_routed_to_dlq() -> None:
    broker, fake = _broker()

    def _broken(message: BrokerMessage) -> None:
        raise RuntimeError("poisonous payload")

    ok = process_with_retries(
        broker, _msg(), _broken, max_retries=2, backoff_base_seconds=0.0
    )

    assert ok is False
    entries = fake.xrange("packet_ingest_dlq")
    assert len(entries) == 1
    import json as _json

    envelope = _json.loads(entries[0][1]["data"])
    assert envelope["error"] == "poisonous payload"
    assert envelope["attempts"] == 2


def test_max_retries_lower_bound_is_one() -> None:
    """``max_retries=0`` is clamped to 1 so the handler runs at least once."""

    broker, fake = _broker()

    def _broken(message: BrokerMessage) -> None:
        raise RuntimeError("nope")

    process_with_retries(
        broker, _msg(), _broken, max_retries=0, backoff_base_seconds=0.0
    )

    assert fake.xlen("packet_ingest_dlq") == 1
