"""Integrity checks for model artifacts before unsafe deserialization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class ModelIntegrityError(RuntimeError):
    """Raised when a model artifact fails manifest verification."""


def load_sha256_manifest(model_dir: Path, filename: str = "manifest.sha256.json") -> dict[str, str]:
    """Read the SHA-256 manifest from ``model_dir``.

    The manifest is intentionally simple JSON:

    ``{"sha256": {"model.pkl": "<hex digest>", ...}}``
    """

    manifest_path = model_dir / filename
    if not manifest_path.exists():
        raise ModelIntegrityError(f"Required model integrity manifest missing: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelIntegrityError(f"Model integrity manifest is not valid JSON: {manifest_path}") from exc

    raw_hashes = payload.get("sha256")
    if not isinstance(raw_hashes, dict):
        raise ModelIntegrityError("Model integrity manifest must contain a 'sha256' object")

    manifest: dict[str, str] = {}
    for name, digest in raw_hashes.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ModelIntegrityError("Model integrity manifest entries must be string:string pairs")
        normalized = digest.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ModelIntegrityError(f"Invalid SHA-256 digest for artifact '{name}'")
        manifest[name] = normalized
    return manifest


def verify_artifact_sha256(path: Path, manifest: dict[str, str]) -> None:
    """Fail unless ``path`` exactly matches its SHA-256 manifest entry."""

    relative_name = path.name
    expected = manifest.get(relative_name)
    if expected is None:
        raise ModelIntegrityError(f"Artifact '{relative_name}' is missing from SHA-256 manifest")

    hasher = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError as exc:
        raise ModelIntegrityError(f"Could not read model artifact for hashing: {path}") from exc

    observed = hasher.hexdigest()
    if observed != expected:
        raise ModelIntegrityError(
            f"SHA-256 mismatch for artifact '{relative_name}': "
            f"expected {expected}, observed {observed}"
        )
