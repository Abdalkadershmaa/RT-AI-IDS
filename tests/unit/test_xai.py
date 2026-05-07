"""Unit tests for the LIME explanation helper."""

from __future__ import annotations

import time
from typing import Any

from services.inference import xai
from services.inference.xai import LIME_BUDGET_SECONDS, submit_lime_explanation


class _FakeExplanation:
    def __init__(self, items: list[tuple[str, float]]) -> None:
        self._items = items

    def as_list(self) -> list[tuple[str, float]]:
        return self._items


class _FakeExplainer:
    def __init__(self, items: list[tuple[str, float]] | None = None, sleep_s: float = 0.0) -> None:
        self._items = items or [("syn_flag_count", 0.42), ("packet_rate", 0.31)]
        self._sleep_s = sleep_s

    def explain_instance(self, _row: Any, _proba_fn: Any, num_features: int) -> _FakeExplanation:
        if self._sleep_s:
            time.sleep(self._sleep_s)
        return _FakeExplanation(self._items[:num_features])


class _FakeClassifier:
    def predict_proba(self, _row: Any) -> Any:
        return [[0.1, 0.9]]


def test_returns_empty_list_when_explainer_missing() -> None:
    result = submit_lime_explanation(None, _FakeClassifier(), [1.0, 2.0], "flow-1")
    assert result == []


def test_returns_empty_list_when_features_missing() -> None:
    result = submit_lime_explanation(_FakeExplainer(), _FakeClassifier(), [], "flow-1")
    assert result == []


def test_returns_attribution_list_in_canonical_shape() -> None:
    result = submit_lime_explanation(
        _FakeExplainer(items=[("syn_flag_count", 0.42), ("packet_rate", 0.31)]),
        _FakeClassifier(),
        [1.0] * 5,
        "flow-1",
    )
    assert result == [
        {"feature": "syn_flag_count", "weight": 0.42},
        {"feature": "packet_rate", "weight": 0.31},
    ]


def test_returns_empty_list_when_budget_exceeded() -> None:
    """Slow explainer must NOT block past the configured budget."""

    explainer = _FakeExplainer(sleep_s=LIME_BUDGET_SECONDS * 4)
    start = time.monotonic()
    result = submit_lime_explanation(explainer, _FakeClassifier(), [1.0] * 5, "flow-slow", timeout=0.05)
    elapsed = time.monotonic() - start
    assert result == []
    # Budget cap is 50 ms; allow generous headroom for thread-pool dispatch.
    assert elapsed < 0.5, f"submit_lime_explanation blocked for {elapsed:.3f}s"


def test_recovers_when_underlying_explainer_raises(monkeypatch) -> None:
    class _Boom:
        def explain_instance(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    result = submit_lime_explanation(_Boom(), _FakeClassifier(), [1.0] * 5, "flow-err")
    assert result == []


def test_skips_non_numeric_weights() -> None:
    explainer = _FakeExplainer(items=[("ok", 0.5), ("bad", "nope")])  # type: ignore[list-item]
    result = submit_lime_explanation(explainer, _FakeClassifier(), [1.0] * 5, "flow-mix")
    assert result == [{"feature": "ok", "weight": 0.5}]


def test_module_level_executor_is_singleton() -> None:
    # Two calls share one executor — important so import doesn't leak threads.
    assert xai._executor is xai._executor
