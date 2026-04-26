"""Test-suite fixtures.

Sets `ENVIRONMENT=test` (which bypasses the production secrets fail-fast),
points DATABASE_URL at a per-process SQLite file, and provides an in-memory
broker fake so tests don't need a real Redis instance.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ALLOW_FALLBACK_CLASSIFIER", "true")
os.environ.setdefault("MODELS_DIR", str(Path(__file__).parent / "_no_models"))


@pytest.fixture
def temp_database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"
    monkeypatch.setenv("DATABASE_URL", url)

    from shared.config import reload_settings
    from shared.db import dispose_engine
    from shared.db.engine import get_engine
    from shared.db.models import Base

    dispose_engine()
    reload_settings()
    Base.metadata.create_all(bind=get_engine())
    try:
        yield url
    finally:
        dispose_engine()
        if os.path.exists(path):
            os.remove(path)


class FakeBroker:
    """Minimal in-memory broker fake used by API tests."""

    def __init__(self) -> None:
        self.published: dict[str, list[dict[str, Any]]] = {}
        self.results: dict[str, dict[str, Any]] = {}

    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        self.published.setdefault(stream, []).append(payload)
        return f"{stream}-{len(self.published[stream])}"

    def consume(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError("FakeBroker does not implement consumption")

    def ack(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        return None

    def store_result(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self.results[key] = json.loads(json.dumps(value))

    def load_result(self, key: str) -> dict[str, Any] | None:
        return self.results.get(key)

    def close(self) -> None:  # pragma: no cover
        return None


@pytest.fixture
def fake_broker() -> Iterator[FakeBroker]:
    from services.api.deps import set_broker

    broker = FakeBroker()
    set_broker(broker)
    try:
        yield broker
    finally:
        set_broker(None)


@pytest.fixture
def api_client(temp_database_url: str, fake_broker: FakeBroker, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")

    from shared.config import reload_settings

    reload_settings()
    from services.api.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()
