from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

try:
    import dill
    import joblib
    import pickle
    from tensorflow import keras
except Exception:  # pragma: no cover
    dill = None
    joblib = None
    pickle = None
    keras = None


@dataclass
class LoadedModels:
    classifier: Any
    ae_scaler: Any
    ae_model: Any
    explainer: Any


class ModelService:
    def __init__(self, model_dir: str = "models") -> None:
        self.model_dir = Path(model_dir)
        self._models: LoadedModels | None = None
        self._lock = Lock()

    def load(self) -> LoadedModels:
        if self._models is not None:
            return self._models
        with self._lock:
            if self._models is not None:
                return self._models
            self._models = self._load_from_disk()
        return self._models

    def _load_from_disk(self) -> LoadedModels:
        classifier = _FallbackClassifier()
        ae_scaler = _IdentityScaler()
        ae_model = _IdentityModel()
        explainer = None

        if pickle and (self.model_dir / "model.pkl").exists():
            with (self.model_dir / "model.pkl").open("rb") as handle:
                classifier = pickle.load(handle)
        if joblib and (self.model_dir / "preprocess_pipeline_AE_39ft.save").exists():
            ae_scaler = joblib.load(self.model_dir / "preprocess_pipeline_AE_39ft.save")
        if keras and (self.model_dir / "autoencoder_39ft.hdf5").exists():
            ae_model = keras.models.load_model(self.model_dir / "autoencoder_39ft.hdf5")
        if dill and (self.model_dir / "explainer").exists():
            with (self.model_dir / "explainer").open("rb") as handle:
                explainer = dill.load(handle)

        return LoadedModels(
            classifier=classifier,
            ae_scaler=ae_scaler,
            ae_model=ae_model,
            explainer=explainer,
        )

    def predict(self, features: list[float]) -> tuple[str, float, float]:
        models = self.load()
        row = np.array([features], dtype=float)
        proba = models.classifier.predict_proba(row).astype(float)
        classification = str(models.classifier.predict(row)[0])
        probability = float(proba.max())
        risk_score = float(np.sum(proba[0, 1:])) if proba.shape[1] > 1 else 0.0
        return classification, probability, risk_score


class _FallbackClassifier:
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

