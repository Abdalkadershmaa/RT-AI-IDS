"""Integration tests for ``GET /api/v1/health/pipeline``.

The probe is JWT-protected and exercises the full publish → consume →
persist → cache loop. The fake broker in conftest.py doesn't actually run
a worker, so these tests stub the worker by writing a result directly to
the broker's result cache for the published job_id.
"""

from __future__ import annotations

import json
import threading
import time

from shared.broker.base import JsonKeyLoad


def _get_token(client) -> str:
    response = client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "admin"},
    )
    assert response.status_code == 200
    return response.get_json()["access_token"]


def _start_fake_worker(broker, ttl: int = 60) -> threading.Thread:
    """Background thread that mimics the inference worker's response.

    Polls the published-streams dict for a ``predict_jobs`` message and
    writes the matching ``predict_results:<job_id>`` cache entry, simulating
    a successful classification.
    """

    stop = threading.Event()

    def _run() -> None:
        seen: set[str] = set()
        while not stop.is_set():
            for stream, payloads in list(broker.published.items()):
                if stream != "predict_jobs":
                    continue
                for payload in payloads:
                    job_id = payload.get("job_id")
                    if not job_id or job_id in seen:
                        continue
                    seen.add(job_id)
                    broker.store_result(
                        f"predict_results:{job_id}",
                        {
                            "job_id": job_id,
                            "status": "completed",
                            "flow_id": payload.get("flow_id"),
                            "classification": "BENIGN",
                            "probability": 0.99,
                            "risk_label": "LOW",
                            "risk_score": 0.1,
                            "rationale": [],
                            "alert_id": 1,
                            "model_version": "v1",
                            "model_dataset": "CICIDS2017",
                            "completed_at": "2025-01-01T00:00:00+00:00",
                        },
                        ttl_seconds=ttl,
                    )
            time.sleep(0.05)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.stop = stop  # type: ignore[attr-defined]
    return thread


def test_pipeline_probe_requires_auth(api_client) -> None:
    response = api_client.get("/api/v1/health/pipeline")
    assert response.status_code == 401


def test_pipeline_probe_returns_ok_when_worker_responds(api_client, fake_broker) -> None:
    worker = _start_fake_worker(fake_broker)
    try:
        token = _get_token(api_client)
        response = api_client.get(
            "/api/v1/health/pipeline",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        worker.stop.set()  # type: ignore[attr-defined]

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    stage_names = [stage["name"] for stage in body["stages"]]
    assert "publish" in stage_names
    assert "inference" in stage_names
    assert "worker" in stage_names
    assert "persist" in stage_names
    assert body["model_version"] == "v1"


def test_pipeline_probe_returns_degraded_on_worker_silence(api_client, fake_broker, monkeypatch) -> None:
    # Force a tiny timeout so the test doesn't sit on the full 5s default.
    monkeypatch.setenv("PIPELINE_PROBE_TIMEOUT_SECONDS", "1")
    from shared.config import reload_settings

    reload_settings()

    token = _get_token(api_client)
    response = api_client.get(
        "/api/v1/health/pipeline",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "degraded"
    inference_stage = next(s for s in body["stages"] if s["name"] == "inference")
    assert inference_stage["status"] == "degraded"


def test_pipeline_probe_reports_down_on_corrupt_cached_result(api_client, fake_broker, monkeypatch) -> None:
    """If the cached predict-result blob is malformed, the probe surfaces it."""

    monkeypatch.setenv("PIPELINE_PROBE_TIMEOUT_SECONDS", "2")
    from shared.config import reload_settings

    reload_settings()

    # Pre-emptively inject a corrupt result for whatever job_id the probe
    # publishes by overriding load_result to return corrupt=True the first
    # time it's called for a probe-* key.
    original_load = fake_broker.load_result
    state = {"called": False}

    def fake_load(key: str) -> JsonKeyLoad:
        if not state["called"] and key.startswith("predict_results:probe-"):
            state["called"] = True
            return JsonKeyLoad(corrupt=True)
        return original_load(key)

    fake_broker.load_result = fake_load  # type: ignore[assignment]

    token = _get_token(api_client)
    response = api_client.get(
        "/api/v1/health/pipeline",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "down"
    # Sanity: the published payload should have a json-serialisable body.
    assert json.dumps(body)
