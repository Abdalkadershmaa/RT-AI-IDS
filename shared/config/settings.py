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
    capture_interface: str | None
    capture_bpf_filter: str | None
    capture_promiscuous: bool
    capture_pcap_file: str | None
    capture_tcpdump_cmd: str | None
    broker_max_stream_len: int
    broker_max_retries: int
    db_pool_size: int
    db_max_overflow: int
    db_pool_timeout: int


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


def _read_optional_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


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
        capture_interface=_read_optional_str("CAPTURE_INTERFACE"),
        capture_bpf_filter=_read_optional_str("CAPTURE_BPF_FILTER"),
        capture_promiscuous=_read_bool("CAPTURE_PROMISCUOUS", default=True),
        capture_pcap_file=_read_optional_str("CAPTURE_PCAP_FILE"),
        capture_tcpdump_cmd=_read_optional_str("CAPTURE_CMD"),
        broker_max_stream_len=int(os.getenv("BROKER_MAX_STREAM_LEN", "100000")),
        broker_max_retries=int(os.getenv("BROKER_MAX_RETRIES", "3")),
        db_pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        db_max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        db_pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    )
    validate_runtime_secrets(
        environment=settings.environment,
        secret_key=settings.secret_key,
        jwt_secret_key=settings.jwt_secret_key,
        admin_password=settings.admin_password,
    )
    _validate_runtime_posture(settings)
    return settings


class InsecureFallbackClassifierError(RuntimeError):
    """Raised when a non-dev environment enables the deterministic stub model."""


def _validate_runtime_posture(settings: Settings) -> None:
    """Reject combinations that are unsafe outside development/test."""

    env = (settings.environment or "").strip().lower()
    if env.startswith("dev") or env == "test":
        return
    if settings.allow_fallback_classifier:
        raise InsecureFallbackClassifierError(
            "Refusing to start: ALLOW_FALLBACK_CLASSIFIER=true is permitted only "
            "in development and test environments. Production must load real "
            "model artifacts from MODELS_DIR."
        )


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
