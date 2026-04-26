"""CORS preflight + actual request behavior."""

from __future__ import annotations

import pytest


@pytest.fixture
def cors_client(temp_database_url, fake_broker, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,https://soc.example.com",
    )

    from shared.config import reload_settings

    reload_settings()
    from services.api.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_preflight_for_allowed_origin_returns_cors_headers(cors_client) -> None:
    response = cors_client.options(
        "/api/v1/predict",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
    assert "POST" in response.headers.get("Access-Control-Allow-Methods", "")
    assert "Authorization" in response.headers.get("Access-Control-Allow-Headers", "")
    assert response.headers.get("Access-Control-Allow-Credentials") == "true"


def test_actual_request_for_allowed_origin_includes_cors_headers(cors_client) -> None:
    response = cors_client.get(
        "/api/v1/health",
        headers={"Origin": "https://soc.example.com"},
    )
    assert response.status_code == 200
    assert response.headers.get("Access-Control-Allow-Origin") == "https://soc.example.com"


def test_request_from_disallowed_origin_omits_cors_headers(cors_client) -> None:
    response = cors_client.get(
        "/api/v1/health",
        headers={"Origin": "https://evil.example.com"},
    )
    assert response.status_code == 200
    # The browser would block this because Allow-Origin is not present.
    assert "Access-Control-Allow-Origin" not in response.headers
