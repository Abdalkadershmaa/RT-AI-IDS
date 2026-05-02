def test_health_endpoint_returns_ok(api_client) -> None:
    response = api_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_ready_endpoint_returns_ready(api_client) -> None:
    response = api_client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"
