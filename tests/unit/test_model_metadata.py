"""Unit tests for the model-version metadata captured per alert."""

from __future__ import annotations

import pytest

from shared.schemas import DetectionResult


def _result() -> DetectionResult:
    return DetectionResult(
        flow_id="flow-1",
        classification="Benign",
        probability=0.9,
        risk_label="minimal",
        risk_score=0.05,
        rationale=[],
        observed_at="2026-04-28T17:00:00+00:00",
    )


def test_persist_alert_records_configured_model_version(
    temp_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_VERSION", "rf-2026-04-15")
    monkeypatch.setenv("MODEL_DATASET", "CICIDS2017+wireless-2026")

    from shared.config import reload_settings

    reload_settings()

    from services.inference.repository import persist_alert

    alert_id = persist_alert(_result(), {"source_ip": "10.0.0.1"})
    assert alert_id > 0

    from shared.db import AttackLog, session_scope

    with session_scope() as session:
        row = session.get(AttackLog, alert_id)
        assert row is not None
        assert row.model_version == "rf-2026-04-15"
        assert row.model_dataset == "CICIDS2017+wireless-2026"


def test_to_dict_surfaces_model_metadata(
    temp_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_VERSION", "rf-canary-1")
    monkeypatch.setenv("MODEL_DATASET", "synthetic")

    from shared.config import reload_settings

    reload_settings()

    from services.inference.repository import persist_alert

    alert_id = persist_alert(_result(), {"source_ip": "10.0.0.1"})

    from shared.db import AttackLog, session_scope

    with session_scope() as session:
        row = session.get(AttackLog, alert_id)
        assert row is not None
        payload = row.to_dict()
    assert payload["model_version"] == "rf-canary-1"
    assert payload["model_dataset"] == "synthetic"


def test_default_model_version_is_unknown(
    temp_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MODEL_VERSION", raising=False)
    monkeypatch.delenv("MODEL_DATASET", raising=False)

    from shared.config import reload_settings

    reload_settings()

    from services.inference.repository import persist_alert

    alert_id = persist_alert(_result(), {})

    from shared.db import AttackLog, session_scope

    with session_scope() as session:
        row = session.get(AttackLog, alert_id)
        assert row is not None
        assert row.model_version == "unknown"
        assert row.model_dataset == "CICIDS2017"
