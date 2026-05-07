"""Unit tests for the audit-log helper and ORM model."""

from __future__ import annotations

import pytest

from services.api.audit import record_audit_event
from shared.db import AuditLog, session_scope

pytestmark = pytest.mark.usefixtures("temp_database_url")


def test_record_audit_event_persists_row() -> None:
    audit_id = record_audit_event(
        actor="admin",
        action="tenant.suspend",
        target="tenant-42",
        payload={"reason": "non-payment"},
    )
    assert isinstance(audit_id, int)

    with session_scope() as session:
        row = session.get(AuditLog, audit_id)
        assert row is not None
        assert row.actor == "admin"
        assert row.action == "tenant.suspend"
        assert row.target == "tenant-42"
        assert row.payload == {"reason": "non-payment"}
        assert row.ts is not None
        assert row.id == audit_id


def test_record_audit_event_handles_payload_default() -> None:
    audit_id = record_audit_event(actor=None, action="system.boot")
    assert isinstance(audit_id, int)

    with session_scope() as session:
        row = session.get(AuditLog, audit_id)
        assert row is not None
        assert row.payload == {}
        assert row.actor is None
        assert row.target is None


def test_audit_log_to_dict_round_trip() -> None:
    audit_id = record_audit_event(
        actor="admin",
        action="login.success",
        target="admin",
        payload={"ip": "10.0.0.1"},
    )
    with session_scope() as session:
        row = session.get(AuditLog, audit_id)
        rendered = row.to_dict()  # type: ignore[union-attr]
    assert rendered["action"] == "login.success"
    assert rendered["payload"] == {"ip": "10.0.0.1"}
    assert isinstance(rendered["ts"], str)
