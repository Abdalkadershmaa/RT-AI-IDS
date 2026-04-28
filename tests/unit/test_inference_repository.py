"""Tests for the inference persistence layer.

Covers the public-API canonical names (``source_ip``/``destination_ip``) as
well as backward-compatible internal names (``src_ip``/``dst_ip`` emitted by
the flow-builder pipeline). The DB column names are the canonical form, so
both inputs must land in the same row.
"""

from __future__ import annotations

import pytest

from services.inference.repository import _coalesce


def test_coalesce_prefers_canonical_name() -> None:
    ctx = {"source_ip": "10.0.0.1", "src_ip": "192.168.1.1"}
    assert _coalesce(ctx, "source_ip", "src_ip") == "10.0.0.1"


def test_coalesce_falls_back_to_legacy_name() -> None:
    ctx = {"src_ip": "192.168.1.1"}
    assert _coalesce(ctx, "source_ip", "src_ip") == "192.168.1.1"


def test_coalesce_empty_string_treated_as_missing() -> None:
    ctx = {"source_ip": "", "src_ip": "192.168.1.1"}
    assert _coalesce(ctx, "source_ip", "src_ip") == "192.168.1.1"


def test_coalesce_returns_default_when_all_missing() -> None:
    assert _coalesce({}, "source_ip", "src_ip", default="unknown") == "unknown"


def test_persist_alert_accepts_canonical_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """When callers send ``source_ip``/``destination_ip`` the row is populated."""

    pytest.importorskip("sqlalchemy")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from shared.db import dispose_engine
    from shared.db.models import Base

    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SECRET_KEY", "test")
    monkeypatch.setenv("JWT_SECRET_KEY", "test")
    monkeypatch.setenv("ADMIN_PASSWORD", "test")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    from shared.config import reload_settings

    reload_settings()
    dispose_engine()

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    monkeypatch.setattr("shared.db.engine._engine", engine, raising=False)
    monkeypatch.setattr("shared.db.engine._sessionmaker", SessionLocal, raising=False)

    from services.inference.repository import persist_alert
    from shared.schemas import DetectionResult

    result = DetectionResult(
        flow_id="flow-1",
        classification="DDoS",
        probability=0.92,
        risk_label="high",
        risk_score=0.81,
        rationale=[],
        observed_at="2025-01-01T00:00:00+00:00",
    )

    new_id = persist_alert(
        result,
        {
            "source_ip": "10.0.0.1",
            "source_port": 1234,
            "destination_ip": "10.0.0.2",
            "destination_port": 80,
            "protocol": "TCP",
        },
    )

    from shared.db import AttackLog

    with SessionLocal() as session:
        row = session.get(AttackLog, new_id)
    assert row is not None
    assert row.source_ip == "10.0.0.1"
    assert row.source_port == 1234
    assert row.destination_ip == "10.0.0.2"
    assert row.destination_port == 80


def test_persist_alert_accepts_legacy_internal_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """``src_ip``/``dst_ip`` emitted by the flow pipeline still populate the row."""

    pytest.importorskip("sqlalchemy")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from shared.db import dispose_engine
    from shared.db.models import Base

    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SECRET_KEY", "test")
    monkeypatch.setenv("JWT_SECRET_KEY", "test")
    monkeypatch.setenv("ADMIN_PASSWORD", "test")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    from shared.config import reload_settings

    reload_settings()
    dispose_engine()

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    monkeypatch.setattr("shared.db.engine._engine", engine, raising=False)
    monkeypatch.setattr("shared.db.engine._sessionmaker", SessionLocal, raising=False)

    from services.inference.repository import persist_alert
    from shared.schemas import DetectionResult

    result = DetectionResult(
        flow_id="flow-2",
        classification="PortScan",
        probability=0.77,
        risk_label="medium",
        risk_score=0.61,
        rationale=[],
        observed_at="2025-01-01T00:00:00+00:00",
    )

    new_id = persist_alert(
        result,
        {
            "src_ip": "172.16.0.1",
            "src_port": 4444,
            "dst_ip": "172.16.0.2",
            "dst_port": 22,
            "protocol": "TCP",
        },
    )

    from shared.db import AttackLog

    with SessionLocal() as session:
        row = session.get(AttackLog, new_id)
    assert row is not None
    assert row.source_ip == "172.16.0.1"
    assert row.source_port == 4444
    assert row.destination_ip == "172.16.0.2"
    assert row.destination_port == 22
