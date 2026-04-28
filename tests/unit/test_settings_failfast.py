"""Settings layer should refuse to start with placeholder secrets in prod."""

from __future__ import annotations

import pytest

from shared.config import InsecureFallbackClassifierError, reload_settings
from shared.security.secrets_validation import InsecureDefaultSecretError


def _real_prod_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "Z9zE0fOLjYBkr7CgT2u6XMmeqRrcYrRk")
    monkeypatch.setenv("JWT_SECRET_KEY", "wH47R9XkR1Al2Y8mxfeF5zvmCh4xrmNb")
    monkeypatch.setenv("ADMIN_PASSWORD", "Sup3rSecre7Pa55w0rd!")


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
    monkeypatch.setenv("ALLOW_FALLBACK_CLASSIFIER", "false")
    settings = reload_settings()
    assert settings.environment == "production"


def test_dev_environment_bypasses_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", "change-me-in-production")
    monkeypatch.setenv("JWT_SECRET_KEY", "change-me-in-production")
    monkeypatch.setenv("ADMIN_PASSWORD", "change-me-in-production")
    reload_settings()  # should not raise


def test_fallback_classifier_rejected_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """ALLOW_FALLBACK_CLASSIFIER=true is forbidden outside development/test."""

    _real_prod_secrets(monkeypatch)
    monkeypatch.setenv("ALLOW_FALLBACK_CLASSIFIER", "true")
    with pytest.raises(InsecureFallbackClassifierError):
        reload_settings()


def test_fallback_classifier_allowed_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", "dev")
    monkeypatch.setenv("JWT_SECRET_KEY", "dev")
    monkeypatch.setenv("ADMIN_PASSWORD", "dev")
    monkeypatch.setenv("ALLOW_FALLBACK_CLASSIFIER", "true")
    settings = reload_settings()
    assert settings.allow_fallback_classifier is True


def test_fallback_classifier_allowed_in_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SECRET_KEY", "test")
    monkeypatch.setenv("JWT_SECRET_KEY", "test")
    monkeypatch.setenv("ADMIN_PASSWORD", "test")
    monkeypatch.setenv("ALLOW_FALLBACK_CLASSIFIER", "true")
    settings = reload_settings()
    assert settings.allow_fallback_classifier is True


def test_fallback_classifier_off_is_safe_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _real_prod_secrets(monkeypatch)
    monkeypatch.setenv("ALLOW_FALLBACK_CLASSIFIER", "false")
    settings = reload_settings()
    assert settings.allow_fallback_classifier is False
    assert settings.environment == "production"


def test_db_pool_settings_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", "dev")
    monkeypatch.setenv("JWT_SECRET_KEY", "dev")
    monkeypatch.setenv("ADMIN_PASSWORD", "dev")
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)
    monkeypatch.delenv("DB_POOL_TIMEOUT", raising=False)
    monkeypatch.delenv("BROKER_MAX_STREAM_LEN", raising=False)
    monkeypatch.delenv("BROKER_MAX_RETRIES", raising=False)
    settings = reload_settings()
    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 10
    assert settings.db_pool_timeout == 30
    assert settings.broker_max_stream_len == 100_000
    assert settings.broker_max_retries == 3


def test_tier2_settings_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rate limit, retention, and model-metadata defaults are well-defined."""

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", "dev")
    monkeypatch.setenv("JWT_SECRET_KEY", "dev")
    monkeypatch.setenv("ADMIN_PASSWORD", "dev")
    for name in ("AUTH_RATE_LIMIT", "ATTACK_LOG_RETENTION_DAYS", "MODEL_VERSION", "MODEL_DATASET"):
        monkeypatch.delenv(name, raising=False)
    settings = reload_settings()
    assert settings.auth_rate_limit == "5 per minute"
    assert settings.attack_log_retention_days == 90
    assert settings.model_version == "unknown"
    assert settings.model_dataset == "CICIDS2017"


def test_tier2_settings_respect_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", "dev")
    monkeypatch.setenv("JWT_SECRET_KEY", "dev")
    monkeypatch.setenv("ADMIN_PASSWORD", "dev")
    monkeypatch.setenv("AUTH_RATE_LIMIT", "10 per hour")
    monkeypatch.setenv("ATTACK_LOG_RETENTION_DAYS", "30")
    monkeypatch.setenv("MODEL_VERSION", "rf-2026-04")
    monkeypatch.setenv("MODEL_DATASET", "synthetic-v2")
    settings = reload_settings()
    assert settings.auth_rate_limit == "10 per hour"
    assert settings.attack_log_retention_days == 30
    assert settings.model_version == "rf-2026-04"
    assert settings.model_dataset == "synthetic-v2"
