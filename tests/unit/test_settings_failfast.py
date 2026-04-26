"""Settings layer should refuse to start with placeholder secrets in prod."""

from __future__ import annotations

import pytest

from shared.config import reload_settings
from shared.security.secrets_validation import InsecureDefaultSecretError


def test_default_secrets_rejected_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "change-me-in-production")
    monkeypatch.setenv("JWT_SECRET_KEY", "change-me-in-production")
    monkeypatch.setenv("ADMIN_PASSWORD", "change-me-in-production")
    with pytest.raises(InsecureDefaultSecretError):
        reload_settings()


def test_real_secrets_accepted_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "Z9zE0fOLjYBkr7CgT2u6XMmeqRrcYrRk")
    monkeypatch.setenv("JWT_SECRET_KEY", "wH47R9XkR1Al2Y8mxfeF5zvmCh4xrmNb")
    monkeypatch.setenv("ADMIN_PASSWORD", "Sup3rSecre7Pa55w0rd!")
    settings = reload_settings()
    assert settings.environment == "production"


def test_dev_environment_bypasses_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", "change-me-in-production")
    monkeypatch.setenv("JWT_SECRET_KEY", "change-me-in-production")
    monkeypatch.setenv("ADMIN_PASSWORD", "change-me-in-production")
    reload_settings()  # should not raise
