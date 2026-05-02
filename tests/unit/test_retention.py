"""Unit tests for the attack-log retention helper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.api.retention import prune_old_alerts


def _seed_alerts(temp_database_url: str) -> None:
    """Insert a handful of alerts spanning a wide created_at range."""

    from shared.db import AttackLog, session_scope

    now = datetime.now(tz=UTC)
    rows = [
        ("very-old", now - timedelta(days=180)),
        ("old", now - timedelta(days=60)),
        ("recent", now - timedelta(days=5)),
        ("brand-new", now - timedelta(hours=1)),
    ]
    with session_scope() as session:
        for flow_id, created_at in rows:
            session.add(
                AttackLog(
                    flow_id=flow_id,
                    source_ip="10.0.0.1",
                    source_port=1234,
                    destination_ip="10.0.0.2",
                    destination_port=80,
                    protocol="TCP",
                    classification="Benign",
                    probability=0.99,
                    risk_label="minimal",
                    risk_score=0.05,
                    rationale=[],
                    created_at=created_at,
                )
            )


def test_prune_disabled_when_retention_is_zero(temp_database_url: str) -> None:
    """A retention of 0 is the explicit "keep forever" sentinel."""

    _seed_alerts(temp_database_url)
    deleted = prune_old_alerts(0)
    assert deleted == 0

    from shared.db import AttackLog, session_scope

    with session_scope() as session:
        assert session.query(AttackLog).count() == 4


def test_prune_disabled_when_retention_is_negative(temp_database_url: str) -> None:
    _seed_alerts(temp_database_url)
    assert prune_old_alerts(-1) == 0

    from shared.db import AttackLog, session_scope

    with session_scope() as session:
        assert session.query(AttackLog).count() == 4


def test_prune_deletes_only_rows_older_than_window(temp_database_url: str) -> None:
    """A 30-day window keeps the recent + brand-new rows and drops the rest."""

    _seed_alerts(temp_database_url)
    deleted = prune_old_alerts(30)
    assert deleted == 2

    from shared.db import AttackLog, session_scope

    with session_scope() as session:
        flow_ids = {row.flow_id for row in session.query(AttackLog).all()}
    assert flow_ids == {"recent", "brand-new"}


def test_prune_with_long_window_keeps_everything(temp_database_url: str) -> None:
    _seed_alerts(temp_database_url)
    deleted = prune_old_alerts(365)
    assert deleted == 0

    from shared.db import AttackLog, session_scope

    with session_scope() as session:
        assert session.query(AttackLog).count() == 4


def test_prune_is_idempotent(temp_database_url: str) -> None:
    """Running prune twice deletes the same rows once and is a no-op the second time."""

    _seed_alerts(temp_database_url)
    first = prune_old_alerts(30)
    second = prune_old_alerts(30)
    assert first == 2
    assert second == 0


def test_prune_handles_empty_table(temp_database_url: str) -> None:
    deleted = prune_old_alerts(30)
    assert deleted == 0


def test_prune_cli_command_runs(temp_database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Flask CLI command exposes the helper for cron / systemd timers."""

    monkeypatch.setenv("ATTACK_LOG_RETENTION_DAYS", "30")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")

    from shared.config import reload_settings

    reload_settings()

    _seed_alerts(temp_database_url)

    from services.api.app import create_app

    app = create_app()
    runner = app.test_cli_runner()
    result = runner.invoke(args=["retention-prune"])
    assert result.exit_code == 0
    assert "Deleted 2 alert(s)" in result.output

    from shared.db import AttackLog, session_scope

    with session_scope() as session:
        assert session.query(AttackLog).count() == 2
