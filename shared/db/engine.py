"""SQLAlchemy engine + session-factory helpers (no Flask).

The engine is process-cached. Tests can call :func:`dispose_engine` to drop
the cached engine before swapping ``DATABASE_URL`` between cases.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from shared.config import get_settings

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def _engine_kwargs(database_url: str) -> dict[str, Any]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}, "future": True}
    return {
        "future": True,
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
    }


def get_engine() -> Engine:
    """Return a process-cached SQLAlchemy engine."""

    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))
        _sessionmaker = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    """Return a process-cached :class:`sessionmaker`."""

    global _sessionmaker
    if _sessionmaker is None:
        get_engine()
    if _sessionmaker is None:  # pragma: no cover - get_engine() always sets this
        raise RuntimeError("Database session factory failed to initialize")
    return _sessionmaker


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a transactional session, committing on success and rolling back on error."""

    factory = get_sessionmaker()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    """Drop the cached engine; the next call to :func:`get_engine` rebuilds it."""

    global _engine, _sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None
