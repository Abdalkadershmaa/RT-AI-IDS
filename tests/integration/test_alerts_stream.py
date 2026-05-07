"""Server-Sent Events tests for ``GET /api/v1/alerts/stream``.

Verifies the demo-critical contract:

* Unauthenticated requests are rejected.
* The legacy ``?access_token=`` query string is still accepted but
  marked with a ``Deprecation:`` response header.
* The new nonce-exchange flow (``POST /api/v1/alerts/subscribe`` →
  ``GET /api/v1/alerts/stream?nonce=<nonce>``) authenticates the SSE
  connection without leaking the long-lived JWT into access logs.
* Rows already in the table are emitted on subscribe (so a late-joining
  dashboard catches up instead of starting blank).
* Each row is emitted as exactly one ``data:`` SSE frame whose payload
  parses as the expected ``AttackLog.to_dict()`` shape and includes the
  additive ``severity``/``type``/``confidence``/``explanation`` fields.
* The response headers are SSE-compliant (``text/event-stream``,
  ``Cache-Control: no-cache``, ``X-Accel-Buffering: no``).

The Redis pub/sub steady-state loop is patched per-test so the catch-up
phase is the only thing that runs and the generator exits deterministically.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from services.api import sse_nonce
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
                risk_label="very_high",
                risk_score=0.9,
                rationale=["ml_model_flagged_flow"],
                explanation=[{"feature": "syn_flag_count", "weight": 0.42}],
                created_at=datetime(2026, 4, 26, 12, 0, i, tzinfo=UTC),
            )
            session.add(row)
            session.flush()
            ids.append(row.id)
    return ids


def _patch_pubsub_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``listen_alerts`` with a generator that exits immediately."""

    def empty_iterator(**_kwargs: Any) -> Iterator[None]:
        return iter([])

    monkeypatch.setattr(alerts_module, "listen_alerts", empty_iterator)


def _consume(response, max_frames: int = 50) -> list[str]:
    frames: list[str] = []
    buffer = ""
    iterator = iter(response.response)
    while True:
        try:
            chunk = next(iterator)
        except StopIteration:
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


def test_stream_accepts_legacy_access_token_with_deprecation_header(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(2)
    token = _get_token(api_client)
    _patch_pubsub_idle(monkeypatch)

    response = api_client.get(f"/api/v1/alerts/stream?access_token={token}")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.headers.get("Cache-Control", "").startswith("no-cache")
    assert response.headers.get("X-Accel-Buffering") == "no"
    # Legacy auth surfaces a Deprecation header per RFC 8594-style.
    assert response.headers.get("Deprecation") == "true"

    frames = _consume(response, max_frames=10)
    assert frames, "expected at least one SSE frame"
    assert frames[0].startswith(": connected"), frames[0]
    data_frames = [f for f in frames if "\ndata:" in f or f.startswith("data:")]
    assert len(data_frames) >= 2, f"expected 2 alerts seeded, got frames={frames}"
    # Verify the alert payload carries the additive fields the frontend
    # consumes (severity uppercase, type, confidence, explanation).
    body = data_frames[0].split("data: ", 1)[1]
    payload = json.loads(body)
    assert payload["severity"] == "CRITICAL"
    assert payload["type"] == "DoS Hulk"
    assert payload["confidence"] == pytest.approx(95.0)
    assert payload["explanation"] == [{"feature": "syn_flag_count", "weight": 0.42}]


def test_subscribe_then_stream_with_nonce(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nonce-exchange flow: POST /alerts/subscribe → SSE ?nonce=<>."""

    _seed(1)
    token = _get_token(api_client)
    sse_nonce.reset_for_tests()
    _patch_pubsub_idle(monkeypatch)

    subscribe_response = api_client.post(
        "/api/v1/alerts/subscribe",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert subscribe_response.status_code == 200
    body = subscribe_response.get_json()
    nonce = body["nonce"]
    assert isinstance(nonce, str) and nonce
    assert body["expires_in"] >= 1

    response = api_client.get(f"/api/v1/alerts/stream?nonce={nonce}")
    assert response.status_code == 200
    # Nonce path does NOT mark the response deprecated.
    assert "Deprecation" not in response.headers
    frames = _consume(response, max_frames=10)
    assert any("data:" in f for f in frames), frames


def test_nonce_is_single_use(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Once consumed, the same nonce must NOT authenticate a second SSE request."""

    _seed(1)
    token = _get_token(api_client)
    sse_nonce.reset_for_tests()
    _patch_pubsub_idle(monkeypatch)

    body = api_client.post(
        "/api/v1/alerts/subscribe",
        headers={"Authorization": f"Bearer {token}"},
    ).get_json()
    nonce = body["nonce"]

    first = api_client.get(f"/api/v1/alerts/stream?nonce={nonce}")
    _consume(first, max_frames=5)
    assert first.status_code == 200

    second = api_client.get(f"/api/v1/alerts/stream?nonce={nonce}")
    assert second.status_code == 401


def test_stream_since_id_skips_existing_rows(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = _seed(3)
    token = _get_token(api_client)
    _patch_pubsub_idle(monkeypatch)

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
