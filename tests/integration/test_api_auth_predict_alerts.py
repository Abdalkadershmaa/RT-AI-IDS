"""Integration tests for the API's async-predict path."""

from __future__ import annotations


def _get_token(client) -> str:
    response = client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "admin"},
    )
    assert response.status_code == 200
    return response.get_json()["access_token"]


def test_auth_token_issued_for_bootstrap_user(api_client) -> None:
    response = api_client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "admin"},
    )
    assert response.status_code == 200
    assert "access_token" in response.get_json()


def test_logout_revokes_current_jwt(api_client) -> None:
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = api_client.delete("/api/v1/auth/logout", headers=headers)

    assert response.status_code == 200
    assert response.get_json()["status"] == "logged_out"

    revoked_response = api_client.get("/api/v1/stats", headers=headers)
    assert revoked_response.status_code == 401
    assert revoked_response.get_json()["error"] == "token_revoked"


def test_predict_returns_202_with_job_id(api_client, fake_broker) -> None:
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = api_client.post(
        "/api/v1/predict",
        json={
            "features": [0.1] * 39,
            "context": {
                "src_ip": "10.0.0.1",
                "src_port": 5151,
                "dst_ip": "10.0.0.2",
                "dst_port": 443,
                "protocol": "TCP",
            },
        },
        headers=headers,
    )

    assert response.status_code == 202
    body = response.get_json()
    assert body["status"] == "pending"
    job_id = body["job_id"]
    assert job_id

    published = fake_broker.published.get("predict_jobs", [])
    assert len(published) == 1
    job = published[0]
    assert job["job_id"] == job_id
    assert len(job["features"]) == 39


def test_predict_result_polling_returns_cached_result(api_client, fake_broker) -> None:
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    enqueue = api_client.post(
        "/api/v1/predict",
        json={"features": [0.0] * 39},
        headers=headers,
    ).get_json()
    job_id = enqueue["job_id"]

    # Worker would normally write this; we simulate it.
    fake_broker.store_result(
        f"predict_results:{job_id}",
        {
            "job_id": job_id,
            "status": "completed",
            "flow_id": "flow-1",
            "classification": "Benign",
            "probability": 0.91,
            "risk_label": "low",
            "risk_score": 0.05,
            "rationale": ["clean_baseline"],
            "alert_id": 42,
        },
        ttl_seconds=60,
    )

    response = api_client.get(f"/api/v1/predict/{job_id}", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "completed"
    assert body["alert_id"] == 42


def test_predict_result_polling_returns_202_while_pending(api_client) -> None:
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    enqueue = api_client.post(
        "/api/v1/predict",
        json={"features": [0.0] * 39},
        headers=headers,
    ).get_json()

    response = api_client.get(f"/api/v1/predict/{enqueue['job_id']}", headers=headers)
    assert response.status_code == 202
    body = response.get_json()
    assert body["status"] == "pending"
    assert body["job_id"] == enqueue["job_id"]


def test_predict_result_404_for_unknown_job(api_client) -> None:
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}
    response = api_client.get("/api/v1/predict/does-not-exist", headers=headers)
    assert response.status_code == 404


def test_protected_routes_require_jwt(api_client) -> None:
    assert api_client.get("/api/v1/alerts").status_code == 401
    assert api_client.get("/api/v1/stats").status_code == 401


def test_predict_validates_feature_count(api_client) -> None:
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}
    response = api_client.post(
        "/api/v1/predict",
        json={"features": [0.1, 0.2]},
        headers=headers,
    )
    assert response.status_code == 400


def test_predict_rejects_nan(api_client) -> None:
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}
    features = [0.1] * 38 + [float("nan")]
    response = api_client.post(
        "/api/v1/predict",
        json={"features": features},
        headers=headers,
    )
    assert response.status_code == 400


def test_stats_returns_zero_when_db_empty(api_client) -> None:
    token = _get_token(api_client)
    headers = {"Authorization": f"Bearer {token}"}
    response = api_client.get("/api/v1/stats", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["total_alerts"] == 0
    assert body["risk_distribution"] == {}
