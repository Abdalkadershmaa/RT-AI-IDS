"""Integration tests for the structured-error envelope.

Every API error response — whether produced by a route, the JWT loader, the
rate limiter, or Werkzeug — must conform to ``{error, status, detail?}`` so
the React/Flutter clients can use a single parser.
"""

from __future__ import annotations


def test_unknown_route_returns_envelope(api_client) -> None:
    response = api_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.get_json()
    assert body["error"] == "not_found"
    assert body["status"] == 404


def test_method_not_allowed_returns_envelope(api_client) -> None:
    response = api_client.delete("/api/v1/auth/token")
    assert response.status_code == 405
    body = response.get_json()
    assert body["error"] == "method_not_allowed"
    assert body["status"] == 405


def test_missing_jwt_returns_envelope(api_client) -> None:
    response = api_client.get("/api/v1/alerts")
    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "unauthorized"
    assert body["status"] == 401


def test_invalid_jwt_returns_envelope(api_client) -> None:
    response = api_client.get(
        "/api/v1/alerts",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "invalid_token"
    assert body["status"] == 401


def test_invalid_credentials_returns_envelope(api_client) -> None:
    response = api_client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "wrong"},
    )
    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "invalid_credentials"
    assert body["status"] == 401


def test_invalid_predict_payload_returns_envelope(api_client) -> None:
    token_response = api_client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "admin"},
    )
    token = token_response.get_json()["access_token"]

    response = api_client.post(
        "/api/v1/predict",
        json={"features": [1.0, 2.0]},  # too short — needs 39
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "invalid_request"
    assert body["status"] == 400
    assert isinstance(body["detail"], list)


def test_predict_result_not_found_returns_envelope(api_client) -> None:
    token_response = api_client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "admin"},
    )
    token = token_response.get_json()["access_token"]

    response = api_client.get(
        "/api/v1/predict/nonexistent-job-id",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    body = response.get_json()
    assert body["error"] == "not_found"
    assert body["status"] == 404
    assert body["detail"] == "job_id unknown or expired"


def test_alert_not_found_returns_envelope(api_client) -> None:
    token_response = api_client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "admin"},
    )
    token = token_response.get_json()["access_token"]

    response = api_client.get(
        "/api/v1/alerts/9999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    body = response.get_json()
    assert body["error"] == "not_found"
    assert body["status"] == 404
