"""Flask extensions used by the API service.

Persistence is intentionally **not** managed through Flask-SQLAlchemy. Routes
talk to the database via :mod:`shared.db.session_scope`, which works
identically inside Flask request handlers and in headless workers.

The rate limiter uses Redis as a shared backend so quotas are enforced across
all gunicorn workers and replicas. When ``REDIS_URL`` points at an
unreachable host the limiter falls back to ``memory://`` (single-process
quotas, with a logged warning) — fine for local pytest runs but not safe for
multi-replica production.

Flask-Limiter is imported lazily so environments that haven't installed it
(e.g. a CI image with the slim test dependency set) can still load the
package without ``ModuleNotFoundError``. When the import fails, ``limiter``
becomes a permissive stub: ``limit(...)`` is a no-op decorator and
``init_limiter()`` does nothing. Production deployments install
``Flask-Limiter`` via ``requirements/api.txt``, so the real limiter is
always active in the gunicorn workers.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from flask_jwt_extended import JWTManager

from shared.config import get_settings

from .jwt_denylist import is_token_revoked

logger = logging.getLogger(__name__)

jwt = JWTManager()


try:  # pragma: no cover - optional in slim CI images
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    _LIMITER_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised only when missing
    Limiter = None  # type: ignore[assignment]
    get_remote_address = None  # type: ignore[assignment]
    _LIMITER_AVAILABLE = False
    logger.warning(
        "flask_limiter_not_installed: rate limiting disabled. Install"
        " Flask-Limiter==3.8.0 (already in requirements/api.txt) to enforce"
        " /auth/token brute-force protection."
    )


class _NoopLimiter:
    """Drop-in stub used when Flask-Limiter isn't installed.

    The ``limit`` decorator returns the wrapped function unchanged so routes
    keep working; ``init_app`` and ``reset`` are no-ops.
    """

    def limit(self, *_args: Any, **_kwargs: Any):  # noqa: D401 - decorator
        def decorator(func):  # type: ignore[no-untyped-def]
            return func

        return decorator

    def init_app(self, _app) -> None:  # type: ignore[no-untyped-def]
        return None

    def reset(self) -> None:
        return None


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


if _LIMITER_AVAILABLE:
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri="memory://",  # replaced in init_limiter() at app creation
        default_limits=[],
        headers_enabled=True,
    )
else:  # pragma: no cover - exercised only when Flask-Limiter is absent
    limiter = _NoopLimiter()  # type: ignore[assignment]


def init_limiter(app) -> None:  # type: ignore[no-untyped-def]
    """Bind the limiter to ``app`` with the resolved storage backend."""

    if not _LIMITER_AVAILABLE:
        return

    storage_uri = _resolve_storage_uri()
    # Reconfigure the singleton's storage; ``init_app`` re-reads from
    # ``app.config`` on each call so we set the URI there.
    app.config["RATELIMIT_STORAGE_URI"] = storage_uri
    app.config["RATELIMIT_HEADERS_ENABLED"] = True
    limiter.init_app(app)


@jwt.token_in_blocklist_loader
def _token_in_blocklist(_jwt_header, jwt_payload):  # type: ignore[no-untyped-def]
    return is_token_revoked(jwt_payload["jti"])
