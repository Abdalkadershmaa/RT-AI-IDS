# Model artifacts

This directory ships pre-trained ML artifacts via Git LFS.

| File                              | Type      | Loaded by               | Currently used? |
| --------------------------------- | --------- | ----------------------- | --------------- |
| `model.pkl`                       | sklearn classifier (pickle) | `ModelService` | **yes** |
| `preprocess_pipeline_AE_39ft.save`| sklearn scaler (joblib)     | `ModelService` | inert (autoencoder path not wired) |
| `autoencoder_39ft.hdf5`           | Keras autoencoder           | `ModelService` | inert |
| `explainer`                       | LIME explainer (dill)       | `ModelService` | inert (XAI path not wired) |
| `scaler.pkl`                      | unknown                     | nothing        | unused — kept pending provenance review |

## Provenance (TODO)

The original training pipeline is not yet committed to this repo. Before
shipping a new artifact set:

1. Capture the training script, dataset hash, and hyperparameters.
2. Place a `MANIFEST.md` here describing each file and its inputs.
3. Add a SHA-256 checksum to `MANIFEST.md` so deployment can verify integrity.

## Loading semantics

`services/inference/model_service.py` is the **only** place that touches
these files. It loads each artifact lazily on first use and caches the
result for the lifetime of the process. In production
(`ALLOW_FALLBACK_CLASSIFIER=false`), missing or unreadable artifacts cause
the inference worker to fail fast at startup.

## Known feature-extraction quirk

The trained classifier consumes a 39-element feature vector produced by
`flow/Flow.py`. That extractor inherits an upstream copy/paste bug: the
`FwdPSHFlags` field is set from the URG flag rather than the PSH flag. We
have **intentionally** retained the bug so the saved model continues to see
the feature distribution it was trained on. See
[docs/architecture.md → Q1](../docs/architecture.md#q1--upstream-urg-vs-psh-bug-in-flowflowpy)
for the retraining plan.
