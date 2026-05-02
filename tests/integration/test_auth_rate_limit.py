"""Integration tests for the rate limiter on ``POST /api/v1/auth/token``.

These tests force a low ``AUTH_RATE_LIMIT`` and verify that:

* requests over the threshold get the canonical structured-error envelope,
* the limit applies to *both* successful and failed credential attempts (so
  brute-force can't slip through by looking at HTTP 401 bodies),
* per-test resets are working (so the suite is order-independent).
"""

from __future__ import annotations

import pytest

# These tests require the real Flask-Limiter package. In the slim CI matrix
# (which doesn't install Flask-Limiter to keep the lint-and-test job fast)
# the API falls back to a no-op limiter and there's nothing to assert here.
pytest.importorskip("flask_limiter", reason="Flask-Limiter not installed in this environment")


@pytest.fixture
def rate_limited_client(temp_database_url, fake_broker, monkeypatch):
    """Boot the API with ``AUTH_RATE_LIMIT=3 per minute`` for a single test."""

    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("AUTH_RATE_LIMIT", "3 per minute")

    from shared.config import reload_settings

    reload_settings()

    from services.api.extensions import limiter

    try:
        limiter.reset()
    except Exception:  # pragma: no cover - storage may not be initialised yet
        pass

    from services.api.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_auth_rate_limit_allows_initial_requests(rate_limited_client) -> None:
    """The first three requests are within budget and go through normally."""

    for _ in range(3):
        response = rate_limited_client.post(
            "/api/v1/auth/token",
            json={"username": "admin", "password": "admin"},
        )
        assert response.status_code == 200


def test_auth_rate_limit_returns_429_envelope_when_exceeded(rate_limited_client) -> None:
    """The fourth request in the window returns 429 with the envelope shape."""

    for _ in range(3):
        rate_limited_client.post(
            "/api/v1/auth/token",
            json={"username": "admin", "password": "admin"},
        )

    response = rate_limited_client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "admin"},
    )

    assert response.status_code == 429
    body = response.get_json()
    assert body["error"] == "too_many_requests"
    assert body["status"] == 429
    # Flask-Limiter sets a Retry-After header so clients can back off.
    assert "Retry-After" in response.headers


def test_auth_rate_limit_counts_failed_credentials(rate_limited_client) -> None:
    """Brute-force attempts (wrong password) consume the same budget."""

    for _ in range(3):
        response = rate_limited_client.post(
            "/api/v1/auth/token",
            json={"username": "admin", "password": "wrong"},
        )
        assert response.status_code == 401

    blocked = rate_limited_client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "wrong"},
    )
    assert blocked.status_code == 429
