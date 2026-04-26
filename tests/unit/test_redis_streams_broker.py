"""Lightweight unit tests for the broker abstraction.

We don't spin up a real Redis here — instead we use ``fakeredis`` if it's
installed. The blocking ``consume`` flow is covered by the live integration
tests run against the dockerized stack; here we exercise the cheap operations
(publish, ack, result cache) that don't depend on consumer-group semantics.
"""

from __future__ import annotations

import pytest

fakeredis = pytest.importorskip("fakeredis")


def _broker():
    from shared.broker.redis_streams import RedisStreamsBroker

    fake = fakeredis.FakeRedis(decode_responses=True)
    broker = RedisStreamsBroker.__new__(RedisStreamsBroker)
    broker._url = "redis://fake"  # type: ignore[attr-defined]
    broker._group = "rt_ai_ids"  # type: ignore[attr-defined]
    broker._client = fake  # type: ignore[attr-defined]
    broker._known_groups = set()  # type: ignore[attr-defined]
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
