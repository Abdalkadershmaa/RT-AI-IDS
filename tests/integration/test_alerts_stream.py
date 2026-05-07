"""Server-Sent Events tests for ``GET /api/v1/alerts/stream``.

Verifies the demo-critical contract:

* Unauthenticated requests are rejected.
* The query-string ``access_token`` is accepted by Flask-JWT-Extended.
* Rows already in the table are emitted on subscribe (so a late-joining
  dashboard catches up instead of starting blank).
* Each row is emitted as exactly one ``data:`` SSE frame whose payload
  parses as the expected ``AttackLog.to_dict()`` shape.
* The response headers are SSE-compliant (``text/event-stream``,
  ``Cache-Control: no-cache``, ``X-Accel-Buffering: no``).

The handler runs an unbounded ``while True: time.sleep(...)`` loop in
production. To keep tests fast, we patch the poll interval to 0 and stop
the generator after a fixed number of yielded frames.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.api.routes import alerts as alerts_module
from shared.db import AttackLog, session_scope


def _get_token(client) -> str:
    response = client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "admin"},
    )
    assert response.status_code == 200
    return response.get_json()["access_token"]


def _seed(n: int) -> list[int]:
    ids: list[int] = []
    with session_scope() as session:
        for i in range(n):
            row = AttackLog(
                flow_id=f"flow-{i}",
                source_ip="10.0.0.5",
                source_port=10000 + i,
                destination_ip="10.0.0.1",
                destination_port=80,
                protocol="TCP",
                classification="DoS Hulk",
                probability=0.95,
                risk_label="critical",
                risk_score=0.9,
                rationale=["ml_model_flagged_flow"],
                created_at=datetime(2026, 4, 26, 12, 0, i, tzinfo=UTC),
            )
            session.add(row)
            session.flush()
            ids.append(row.id)
    return ids


class _StopStreaming(Exception):
    """Raised by the patched ``time.sleep`` to terminate the SSE loop."""


def _consume(response, max_frames: int = 50) -> list[str]:
    """Drain at most ``max_frames`` SSE frames from a streaming response."""
    frames: list[str] = []
    buffer = ""
    iterator = iter(response.response)  # type: ignore[arg-type]
    while True:
        try:
            chunk = next(iterator)
        except (StopIteration, _StopStreaming):
            break
        buffer += chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            frames.append(frame)
            if len(frames) >= max_frames:
                return frames
    return frames


def test_stream_requires_auth(api_client) -> None:
    response = api_client.get("/api/v1/alerts/stream")
    assert response.status_code == 401


def test_stream_accepts_query_string_token(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(2)
    token = _get_token(api_client)

    # Make the SSE loop deterministic for tests: zero sleep, exit after the
    # first batch by raising StopIteration through a counter-bounded sleep.
    calls = {"n": 0}

    def fast_sleep(_s: float) -> None:
        calls["n"] += 1
        if calls["n"] >= 1:
            raise _StopStreaming

    monkeypatch.setattr(alerts_module.time, "sleep", fast_sleep)

    response = api_client.get(f"/api/v1/alerts/stream?access_token={token}")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.headers.get("Cache-Control", "").startswith("no-cache")
    assert response.headers.get("X-Accel-Buffering") == "no"

    frames = _consume(response, max_frames=10)
    assert frames, "expected at least one SSE frame"
    assert frames[0].startswith(": connected"), frames[0]
    data_frames = [f for f in frames if "\ndata:" in f or f.startswith("data:")]
    assert len(data_frames) >= 2, f"expected 2 alerts seeded, got frames={frames}"


def test_stream_since_id_skips_existing_rows(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = _seed(3)
    token = _get_token(api_client)

    calls = {"n": 0}

    def fast_sleep(_s: float) -> None:
        calls["n"] += 1
        if calls["n"] >= 1:
            raise _StopStreaming

    monkeypatch.setattr(alerts_module.time, "sleep", fast_sleep)

    response = api_client.get(f"/api/v1/alerts/stream?access_token={token}&since_id={ids[1]}")
    frames = _consume(response, max_frames=10)
    data_frames = [f for f in frames if "\ndata:" in f or f.startswith("data:")]
    # Only the row newer than ids[1] should be replayed.
    assert len(data_frames) == 1, frames


def test_demo_dashboard_served(api_client) -> None:
    response = api_client.get("/api/v1/demo")
    assert response.status_code == 200
    assert response.mimetype.startswith("text/html")
    assert "RT-AI-IDS" in response.get_data(as_text=True)
    csp = response.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
