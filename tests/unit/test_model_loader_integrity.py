from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from services.inference.model_loader import (
    ModelIntegrityError,
    load_sha256_manifest,
    verify_artifact_sha256,
)
from services.inference.model_service import ModelArtifactIntegrityError, ModelService


def test_load_sha256_manifest_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ModelIntegrityError):
        load_sha256_manifest(tmp_path)


def test_verify_artifact_sha256_rejects_tampering(tmp_path: Path) -> None:
    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"original-bytes")
    manifest = {"model.pkl": "9c56cc51d074e0dcf2d7d4f12e9023f801e0c8edca8f9bb0b5a5b3a7cfb2b9a7"}

    with pytest.raises(ModelIntegrityError):
        verify_artifact_sha256(artifact, manifest)


def test_model_service_refuses_hash_mismatch_before_deserialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"legit-looking-but-tampered")
    (tmp_path / "manifest.sha256.json").write_text(
        '{"sha256": {"model.pkl": "37504408afde6b64b527ca37cddec3a90d769a2c0b68fc6f878266f2ddc92486"}}',
        encoding="utf-8",
    )

    import services.inference.model_service as model_service

    monkeypatch.setattr(
        model_service,
        "pickle",
        SimpleNamespace(load=lambda _handle: pytest.fail("deserialization should not run")),
    )
    monkeypatch.setattr(model_service, "joblib", None)
    monkeypatch.setattr(model_service, "keras", None)
    monkeypatch.setattr(model_service, "dill", None)

    service = ModelService(model_dir=str(tmp_path), allow_fallback=False)

    with pytest.raises(ModelArtifactIntegrityError):
        service.load()
