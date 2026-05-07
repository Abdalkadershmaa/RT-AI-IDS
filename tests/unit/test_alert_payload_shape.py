"""Tests for the additive fields on the alert response payload.

The frontend, Chrome extension, and SIEM-shipper all expect:

* ``severity`` — UPPERCASE tier (CRITICAL/HIGH/MEDIUM/LOW/MINIMAL).
* ``type`` — alias of ``classification``.
* ``confidence`` — ``probability * 100`` rounded to one decimal place.
* ``explanation`` — LIME attribution list, ``[]`` if unavailable.

These are *additive* — every existing field (``risk_label``,
``classification``, ``probability``, ``rationale``) must still be
present so legacy clients keep working.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.db import AttackLog, session_scope
from shared.db.models import severity_for

pytestmark = pytest.mark.usefixtures("temp_database_url")


def _make(risk_label: str, probability: float = 0.94, classification: str = "DoS Hulk") -> int:
    with session_scope() as session:
        row = AttackLog(
            flow_id="flow-1",
            source_ip="10.0.0.5",
            source_port=12345,
            destination_ip="10.0.0.1",
            destination_port=80,
            protocol="TCP",
            classification=classification,
            probability=probability,
            risk_label=risk_label,
            risk_score=probability,
            rationale=["ml_model_flagged_flow"],
            explanation=[{"feature": "syn_flag_count", "weight": 0.42}],
            created_at=datetime.now(tz=UTC),
        )
        session.add(row)
        session.flush()
        return int(row.id)


def _fetch(alert_id: int) -> dict:
    with session_scope() as session:
        row = session.get(AttackLog, alert_id)
        return row.to_dict()  # type: ignore[union-attr]


def test_to_dict_adds_uppercase_severity_for_critical() -> None:
    payload = _fetch(_make("very_high"))
    assert payload["severity"] == "CRITICAL"
    assert payload["risk_label"] == "very_high"


def test_to_dict_adds_uppercase_severity_for_high() -> None:
    payload = _fetch(_make("high"))
    assert payload["severity"] == "HIGH"


def test_to_dict_adds_uppercase_severity_for_medium() -> None:
    payload = _fetch(_make("medium"))
    assert payload["severity"] == "MEDIUM"


def test_to_dict_adds_uppercase_severity_for_low() -> None:
    payload = _fetch(_make("low"))
    assert payload["severity"] == "LOW"


def test_to_dict_adds_uppercase_severity_for_minimal() -> None:
    payload = _fetch(_make("minimal"))
    assert payload["severity"] == "MINIMAL"


def test_to_dict_aliases_classification_as_type() -> None:
    payload = _fetch(_make("high", classification="PortScan"))
    assert payload["type"] == "PortScan"
    assert payload["classification"] == "PortScan"


def test_to_dict_renders_confidence_as_percentage() -> None:
    payload = _fetch(_make("high", probability=0.948))
    assert payload["confidence"] == 94.8
    assert payload["probability"] == pytest.approx(0.948)


def test_to_dict_carries_lime_explanation_list() -> None:
    payload = _fetch(_make("high"))
    assert payload["explanation"] == [{"feature": "syn_flag_count", "weight": 0.42}]


def test_severity_for_helper_handles_unknown_label() -> None:
    assert severity_for(None) == "MINIMAL"
    assert severity_for("") == "MINIMAL"
    assert severity_for("very_high") == "CRITICAL"
    # An unmapped label is uppercased verbatim so callers never silently
    # drop it.
    assert severity_for("custom_tier") == "CUSTOM_TIER"
