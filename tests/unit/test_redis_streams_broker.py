"""Lightweight unit tests for the broker abstraction.

We don't spin up a real Redis here — instead we use ``fakeredis`` if it's
installed. The blocking ``consume`` flow is covered by the live integration
tests run against the dockerized stack; here we exercise the cheap operations
(publish, ack, result cache) that don't depend on consumer-group semantics.
"""

from __future__ import annotations

import pytest

fakeredis = pytest.importorskip("fakeredis")


def _broker(default_maxlen: int = 0):
    from shared.broker.redis_streams import RedisStreamsBroker

    fake = fakeredis.FakeRedis(decode_responses=True)
    broker = RedisStreamsBroker.__new__(RedisStreamsBroker)
    broker._url = "redis://fake"  # type: ignore[attr-defined]
    broker._group = "rt_ai_ids"  # type: ignore[attr-defined]
    broker._client = fake  # type: ignore[attr-defined]
    broker._known_groups = set()  # type: ignore[attr-defined]
    broker._default_maxlen = default_maxlen  # type: ignore[attr-defined]
    return broker, fake


def test_publish_writes_to_stream() -> None:
    broker, fake = _broker()
    msg_id = broker.publish("packet_ingest", {"src": "10.0.0.1"})
    assert msg_id
    assert fake.xlen("packet_ingest") == 1


def test_store_and_load_result() -> None:
    broker, _ = _broker()
    broker.store_result("predict_results:abc", {"job_id": "abc", "status": "completed"}, 60)
    assert broker.load_result("predict_results:abc") == {"job_id": "abc", "status": "completed"}
    assert broker.load_result("missing") is None


def test_ack_is_safe_when_group_missing() -> None:
    broker, _ = _broker()
    # Should not raise even if the group/message don't exist.
    broker.ack("packet_ingest", "1-1")


def test_publish_respects_default_maxlen() -> None:
    """With a default cap of 100, the stream length stays bounded after bursts."""

    broker, fake = _broker(default_maxlen=100)
    for i in range(500):
        broker.publish("packet_ingest", {"i": i})
    # Approximate trim — fakeredis honors the exact MAXLEN, so we expect 100.
    assert fake.xlen("packet_ingest") <= 100


def test_publish_per_call_maxlen_overrides_default() -> None:
    broker, fake = _broker(default_maxlen=100)
    for i in range(20):
        broker.publish("custom", {"i": i}, maxlen=5)
    assert fake.xlen("custom") <= 5


def test_publish_with_zero_maxlen_does_not_trim() -> None:
    broker, fake = _broker(default_maxlen=10)
    for i in range(50):
        broker.publish("custom", {"i": i}, maxlen=0)
    assert fake.xlen("custom") == 50


def test_publish_dlq_writes_envelope() -> None:
    broker, fake = _broker(default_maxlen=0)
    msg_id = broker.publish_dlq(
        original_stream="packet_ingest",
        message_id="1-1",
        payload={"src": "10.0.0.1"},
        error="boom",
        attempts=3,
    )
    assert msg_id
    entries = fake.xrange("packet_ingest_dlq")
    assert len(entries) == 1
    payload_field = entries[0][1]["data"]
    import json as _json

    envelope = _json.loads(payload_field)
    assert envelope["original_stream"] == "packet_ingest"
    assert envelope["original_message_id"] == "1-1"
    assert envelope["error"] == "boom"
    assert envelope["attempts"] == 3
    assert envelope["original_payload"] == {"src": "10.0.0.1"}
