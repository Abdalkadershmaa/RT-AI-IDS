import os
import tempfile

from services.api.app import create_app


def _build_test_app():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    os.environ["ADMIN_USERNAME"] = "admin"
    os.environ["ADMIN_PASSWORD"] = "admin"
    app = create_app()
    app.config["TESTING"] = True
    return app, path


def test_auth_token_issued_for_bootstrap_user():
    app, path = _build_test_app()
    try:
        client = app.test_client()
        response = client.post(
            "/api/v1/auth/token",
            json={"username": "admin", "password": "admin"},
        )
        assert response.status_code == 200
        assert "access_token" in response.get_json()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_predict_creates_alert_and_alerts_endpoint_lists_it():
    app, path = _build_test_app()
    try:
        client = app.test_client()
        token_response = client.post(
            "/api/v1/auth/token",
            json={"username": "admin", "password": "admin"},
        )
        token = token_response.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        predict_response = client.post(
            "/api/v1/predict",
            json={
                "features": [0.1] * 39,
                "context": {
                    "src_ip": "10.0.0.1",
                    "src_port": 5151,
                    "dst_ip": "10.0.0.2",
                    "dst_port": 443,
                    "protocol": "TCP",
                    "wireless": {
                        "link_type": "wifi",
                        "privacy_wep_enabled": True,
                        "wps_enabled": True,
                        "wps_failed_enrollment_attempts": 4,
                    },
                },
            },
            headers=headers,
        )
        assert predict_response.status_code == 201
        created = predict_response.get_json()
        assert created["flow_id"]

        alerts_response = client.get("/api/v1/alerts?limit=10", headers=headers)
        assert alerts_response.status_code == 200
        alerts = alerts_response.get_json()
        assert isinstance(alerts, list)
        assert len(alerts) >= 1
        assert alerts[0]["flow_id"]
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_protected_routes_require_jwt_and_predict_validates_input():
    app, path = _build_test_app()
    try:
        client = app.test_client()
        unauthorized = client.get("/api/v1/alerts")
        assert unauthorized.status_code in (401, 422)
        unauthorized_stats = client.get("/api/v1/stats")
        assert unauthorized_stats.status_code in (401, 422)

        token_response = client.post(
            "/api/v1/auth/token",
            json={"username": "admin", "password": "admin"},
        )
        token = token_response.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        invalid_predict = client.post(
            "/api/v1/predict",
            json={"features": [0.1, 0.2]},
            headers=headers,
        )
        assert invalid_predict.status_code == 400
        authorized_stats = client.get("/api/v1/stats", headers=headers)
        assert authorized_stats.status_code == 200
    finally:
        if os.path.exists(path):
            os.remove(path)

