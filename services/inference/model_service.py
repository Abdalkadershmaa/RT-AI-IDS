"""Singleton ML loader.

A :class:`ModelService` instance keeps a single set of artifacts resident in
memory for the lifetime of the process. Each worker / Gunicorn worker has
exactly one of these objects.

Production behavior is **fail-fast**: if the configured model files cannot be
loaded, :meth:`load` raises :class:`ModelArtifactError`. The legacy stub
classifier is only used when ``ALLOW_FALLBACK_CLASSIFIER=true`` (gated by
:func:`shared.config.get_settings`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from shared.config import get_settings

try:
    import pickle

    import dill
    import joblib
    from tensorflow import keras
except ImportError:  # pragma: no cover - optional in trimmed images
    dill = None  # type: ignore[assignment]
    joblib = None  # type: ignore[assignment]
    pickle = None  # type: ignore[assignment]
    keras = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class ModelArtifactError(RuntimeError):
    """Raised when required model artifacts are missing or unloadable."""


@dataclass
class LoadedModels:
    """Container for every artifact the inference path may need."""

    classifier: Any
    ae_scaler: Any
    ae_model: Any
    explainer: Any
    is_fallback: bool


class ModelService:
    """Process-wide singleton that loads ML artifacts exactly once."""

    def __init__(self, model_dir: str | None = None, allow_fallback: bool | None = None) -> None:
        settings = get_settings()
        self.model_dir = Path(model_dir or settings.models_dir)
        self._allow_fallback = (
            settings.allow_fallback_classifier if allow_fallback is None else allow_fallback
        )
        self._models: LoadedModels | None = None
        self._lock = Lock()

    @property
    def is_loaded(self) -> bool:
        return self._models is not None

    @property
    def is_fallback(self) -> bool:
        return bool(self._models and self._models.is_fallback)

    def load(self) -> LoadedModels:
        """Load the artifact set, caching the result."""

        if self._models is not None:
            return self._models
        with self._lock:
            if self._models is not None:
                return self._models
            self._models = self._load_from_disk()
        return self._models

    def warm_up(self) -> LoadedModels:
        """Eagerly trigger the load. Workers call this on startup."""

        models = self.load()
        if models.is_fallback:
            logger.warning("model_service_using_fallback_classifier")
        else:
            logger.info(
                "model_service_models_loaded",
                extra={"model_dir": str(self.model_dir)},
            )
        return models

    def _load_from_disk(self) -> LoadedModels:
        classifier: Any
        ae_scaler: Any = _IdentityScaler()
        ae_model: Any = _IdentityModel()
        explainer: Any = None

        classifier_path = self.model_dir / "model.pkl"
        classifier = None
        load_error: Exception | None = None
        if pickle and classifier_path.exists():
            try:
                with classifier_path.open("rb") as handle:
                    classifier = pickle.load(handle)
            except Exception as exc:  # noqa: BLE001 — incompatible artefacts surface as many error types
                load_error = exc
                logger.warning(
                    "model_service_classifier_load_failed path=%s error=%s",
                    classifier_path,
                    exc,
                )
        if classifier is None:
            if not self._allow_fallback:
                if load_error is not None:
                    raise ModelArtifactError(
                        f"Failed to load classifier artifact at {classifier_path}: {load_error}. "
                        "Set ALLOW_FALLBACK_CLASSIFIER=true to boot a deterministic stub."
                    ) from load_error
                raise ModelArtifactError(
                    f"Required classifier artifact missing: {classifier_path}. "
                    "Set ALLOW_FALLBACK_CLASSIFIER=true to boot a deterministic stub."
                )
            classifier = _FallbackClassifier()

        scaler_path = self.model_dir / "preprocess_pipeline_AE_39ft.save"
        if joblib and scaler_path.exists():
            try:
                ae_scaler = joblib.load(scaler_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("model_service_scaler_load_failed error=%s", exc)

        ae_path = self.model_dir / "autoencoder_39ft.hdf5"
        if keras and ae_path.exists():
            try:
                ae_model = keras.models.load_model(ae_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("model_service_autoencoder_load_failed error=%s", exc)

        explainer_path = self.model_dir / "explainer"
        if dill and explainer_path.exists():
            try:
                with explainer_path.open("rb") as handle:
                    explainer = dill.load(handle)
            except Exception as exc:  # noqa: BLE001
                logger.warning("model_service_explainer_load_failed error=%s", exc)

        return LoadedModels(
            classifier=classifier,
            ae_scaler=ae_scaler,
            ae_model=ae_model,
            explainer=explainer,
            is_fallback=isinstance(classifier, _FallbackClassifier),
        )

    def predict(self, features: list[float]) -> tuple[str, float, float]:
        """Run the classifier on a single feature vector.

        Returns ``(class_label, max_probability, risk_score)``. ``risk_score``
        is the sum of probabilities for every non-Benign class.
        """

        models = self.load()
        row = np.array([features], dtype=float)
        proba = models.classifier.predict_proba(row).astype(float)
        classification = str(models.classifier.predict(row)[0])
        probability = float(proba.max())
        risk_score = float(np.sum(proba[0, 1:])) if proba.shape[1] > 1 else 0.0
        return classification, probability, risk_score


class _FallbackClassifier:
    """Deterministic stub used only when explicitly allowed."""

    classes_ = np.array(["Benign", "Suspicious"])

    def predict(self, row: np.ndarray) -> np.ndarray:
        return np.array(["Suspicious" if float(np.mean(row)) > 1 else "Benign"])

    def predict_proba(self, row: np.ndarray) -> np.ndarray:
        score = min(max(float(np.mean(np.abs(row))) / 1000.0, 0.0), 1.0)
        return np.array([[1.0 - score, score]])


class _IdentityScaler:
    def transform(self, row: np.ndarray) -> np.ndarray:
        return row


class _IdentityModel:
    def predict(self, row: np.ndarray) -> np.ndarray:
        return row
