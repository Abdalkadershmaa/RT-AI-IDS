"""Cursor-pagination tests for ``GET /api/v1/alerts``.

Locks in the mobile-friendly query semantics added for the Flutter client:

* default behaviour unchanged (newest-first, capped by ``limit``)
* ``since_id`` returns only rows newer than the cursor, ascending
* ``before_id`` returns only rows older than the cursor, newest-first
* the two cursors are mutually exclusive (400 when both provided)
* invalid integer values are rejected (400)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shared.db import AttackLog, session_scope


def _get_token(client) -> str:
    response = client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "admin"},
    )
    assert response.status_code == 200
    return response.get_json()["access_token"]


def _seed_alerts(count: int) -> list[int]:
    base = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
    ids: list[int] = []
    with session_scope() as session:
        for i in range(count):
            row = AttackLog(
                flow_id=f"flow-{i}",
                source_ip="10.0.0.1",
                source_port=1000 + i,
                destination_ip="10.0.0.2",
                destination_port=80,
                protocol="TCP",
                classification="DoS Hulk",
                probability=0.9,
                risk_label="high",
                risk_score=0.7,
                rationale=["ml_model_flagged_flow"],
                created_at=base + timedelta(seconds=i),
            )
            session.add(row)
            session.flush()
            ids.append(row.id)
    return ids


def test_default_returns_newest_first(api_client) -> None:
    seeded = _seed_alerts(5)
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = api_client.get("/api/v1/alerts?limit=10", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert [row["id"] for row in body] == list(reversed(seeded))


def test_since_id_returns_only_newer_rows_ascending(api_client) -> None:
    seeded = _seed_alerts(6)
    cursor = seeded[2]  # third row
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = api_client.get(f"/api/v1/alerts?since_id={cursor}", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    returned = [row["id"] for row in body]
    assert returned == seeded[3:]  # ascending, only rows after the cursor


def test_since_id_zero_returns_everything_ascending(api_client) -> None:
    seeded = _seed_alerts(4)
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = api_client.get("/api/v1/alerts?since_id=0", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert [row["id"] for row in body] == seeded


def test_before_id_returns_older_rows_newest_first(api_client) -> None:
    seeded = _seed_alerts(6)
    cursor = seeded[4]  # fifth row
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = api_client.get(
        f"/api/v1/alerts?before_id={cursor}&limit=10", headers=headers
    )
    assert response.status_code == 200
    body = response.get_json()
    returned = [row["id"] for row in body]
    assert returned == list(reversed(seeded[:4]))


def test_before_id_respects_limit_for_infinite_scroll(api_client) -> None:
    seeded = _seed_alerts(10)
    cursor = seeded[-1]
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = api_client.get(
        f"/api/v1/alerts?before_id={cursor}&limit=3", headers=headers
    )
    assert response.status_code == 200
    body = response.get_json()
    assert [row["id"] for row in body] == [seeded[-2], seeded[-3], seeded[-4]]


def test_since_id_and_before_id_are_mutually_exclusive(api_client) -> None:
    _seed_alerts(3)
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = api_client.get(
        "/api/v1/alerts?since_id=1&before_id=3", headers=headers
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "invalid_request"


def test_negative_since_id_is_rejected(api_client) -> None:
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = api_client.get("/api/v1/alerts?since_id=-1", headers=headers)
    assert response.status_code == 400
