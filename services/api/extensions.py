"""Flask extensions used by the API service.

Persistence is intentionally **not** managed through Flask-SQLAlchemy. Routes
talk to the database via :mod:`shared.db.session_scope`, which works
identically inside Flask request handlers and in headless workers.

The rate limiter uses Redis as a shared backend so quotas are enforced across
all gunicorn workers and replicas. When ``REDIS_URL`` points at an
unreachable host the limiter falls back to ``memory://`` (single-process
quotas, with a logged warning) — fine for local pytest runs but not safe for
multi-replica production.
"""

from __future__ import annotations

import logging
import os

from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from shared.config import get_settings

logger = logging.getLogger(__name__)

jwt = JWTManager()


def _resolve_storage_uri() -> str:
    """Pick a storage backend for the limiter at app-creation time.

    Production points at the same Redis instance the broker uses so quotas
    are enforced across every gunicorn worker and replica. The pytest suite
    sets ``RATE_LIMIT_STORAGE_URI=memory://`` (no real Redis available),
    which Flask-Limiter understands as a single-process in-memory backend.
    """

    override = os.getenv("RATE_LIMIT_STORAGE_URI")
    if override:
        return override
    try:
        return get_settings().redis_url
    except Exception as exc:  # pragma: no cover - settings layer fails fast
        logger.warning("rate_limit_storage_using_memory reason=%s", exc)
        return "memory://"


limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",  # replaced in init_limiter() at app creation
    default_limits=[],
    headers_enabled=True,
)


def init_limiter(app) -> None:  # type: ignore[no-untyped-def]
    """Bind the limiter to ``app`` with the resolved storage backend."""

    storage_uri = _resolve_storage_uri()
    # Reconfigure the singleton's storage; ``init_app`` re-reads from
    # ``app.config`` on each call so we set the URI there.
    app.config["RATELIMIT_STORAGE_URI"] = storage_uri
    app.config["RATELIMIT_HEADERS_ENABLED"] = True
    limiter.init_app(app)
