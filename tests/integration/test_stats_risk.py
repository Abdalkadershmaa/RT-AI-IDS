"""End-to-end test for the dashboard's risk-distribution endpoint.

The risk chart on the frontend reads ``/api/v1/stats/risk`` and expects:

* ``risk_distribution`` keyed by uppercase severity tier
  (``CRITICAL``/``HIGH``/``MEDIUM``/``LOW``/``MINIMAL``).
* All five tiers always present, even with zero counts, so the chart can
  render zero-bars without a follow-up call.
* ``count`` is an integer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from shared.db import AttackLog, session_scope


def _login(client) -> str:
    response = client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "admin"},
    )
    return response.get_json()["access_token"]


def _seed(rows: list[tuple[str, int]]) -> None:
    """Insert ``count`` rows for each ``(risk_label, count)`` tuple."""

    with session_scope() as session:
        for label, count in rows:
            for i in range(count):
                session.add(
                    AttackLog(
                        flow_id=f"{label}-{i}",
                        source_ip="10.0.0.1",
                        source_port=12345,
                        destination_ip="10.0.0.2",
                        destination_port=80,
                        protocol="TCP",
                        classification="Test",
                        probability=0.5,
                        risk_label=label,
                        risk_score=0.5,
                        rationale=[],
                        created_at=datetime.now(tz=UTC),
                    )
                )


def test_stats_risk_returns_five_tiers_in_order(api_client) -> None:
    _seed(
        [
            ("very_high", 3),
            ("high", 2),
            ("medium", 1),
        ]
    )
    token = _login(api_client)
    response = api_client.get("/api/v1/stats/risk", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.get_json()
    distribution = body["risk_distribution"]
    assert [bucket["label"] for bucket in distribution] == [
        "CRITICAL",
        "HIGH",
        "MEDIUM",
        "LOW",
        "MINIMAL",
    ]
    counts = {bucket["label"]: bucket["count"] for bucket in distribution}
    assert counts == {
        "CRITICAL": 3,
        "HIGH": 2,
        "MEDIUM": 1,
        "LOW": 0,
        "MINIMAL": 0,
    }


def test_stats_risk_requires_auth(api_client) -> None:
    response = api_client.get("/api/v1/stats/risk")
    assert response.status_code == 401


def test_stats_risk_returns_zero_buckets_when_empty(api_client) -> None:
    token = _login(api_client)
    response = api_client.get("/api/v1/stats/risk", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.get_json()
    distribution = body["risk_distribution"]
    assert all(bucket["count"] == 0 for bucket in distribution)
    assert len(distribution) == 5
