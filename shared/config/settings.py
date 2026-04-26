"""Centralized runtime configuration.

Loaded from environment variables (and an optional ``.env`` file). The settings
object is evaluated lazily by :func:`get_settings` so test code can mutate
``os.environ`` and call :func:`reload_settings` to pick up the change.

The settings layer is the single place that enforces fail-fast behavior on
placeholder secrets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # pragma: no cover - python-dotenv is in requirements
    pass

from shared.security import validate_runtime_secrets


@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot for one process lifetime."""

    environment: str
    secret_key: str
    jwt_secret_key: str
    database_url: str
    redis_url: str
    ingest_stream: str
    flow_inference_stream: str
    predict_jobs_stream: str
    consumer_group: str
    predict_result_ttl_seconds: int
    admin_username: str
    admin_password: str
    log_level: str
    models_dir: str
    allow_fallback_classifier: bool
    cors_allow_origins: tuple[str, ...]


_cached: Settings | None = None


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_cors_origins(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(origin.strip() for origin in raw.split(",") if origin.strip())


def _build() -> Settings:
    settings = Settings(
        environment=os.getenv("ENVIRONMENT", "development"),
        secret_key=os.getenv("SECRET_KEY", "change-me-in-production"),
        jwt_secret_key=os.getenv("JWT_SECRET_KEY", "change-me-in-production"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///ids.db"),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        ingest_stream=os.getenv("INGEST_STREAM", "packet_ingest"),
        flow_inference_stream=os.getenv("FLOW_INFERENCE_STREAM", "flow_inference"),
        predict_jobs_stream=os.getenv("PREDICT_JOBS_STREAM", "predict_jobs"),
        consumer_group=os.getenv("BROKER_CONSUMER_GROUP", "rt_ai_ids"),
        predict_result_ttl_seconds=int(os.getenv("PREDICT_RESULT_TTL_SECONDS", "3600")),
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("ADMIN_PASSWORD", "change-me-in-production"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        models_dir=os.getenv("MODELS_DIR", "models"),
        allow_fallback_classifier=_read_bool("ALLOW_FALLBACK_CLASSIFIER", default=False),
        cors_allow_origins=_read_cors_origins(os.getenv("CORS_ALLOW_ORIGINS")),
    )
    validate_runtime_secrets(
        environment=settings.environment,
        secret_key=settings.secret_key,
        jwt_secret_key=settings.jwt_secret_key,
        admin_password=settings.admin_password,
    )
    return settings


def get_settings() -> Settings:
    """Return a process-cached :class:`Settings` instance."""

    global _cached
    if _cached is None:
        _cached = _build()
    return _cached


def reload_settings() -> Settings:
    """Force re-read of environment variables (test helper)."""

    global _cached
    _cached = None
    return get_settings()
