# RT-AI-IDS Architecture

## Overview

RT-AI-IDS is a real-time intrusion-detection system structured as four
loosely-coupled services that communicate through Redis Streams:

```
                  ┌────────────┐                       ┌──────────────┐
   network ─────▶ │ ingestion  │ ── packet_ingest ───▶ │ flow_builder │
                  └────────────┘                       └──────┬───────┘
                                                              │ flow_inference
                                                              ▼
   API client ───▶ ┌────────────┐ ── predict_jobs ───▶ ┌──────────────┐
                   │    api     │                      │  inference   │
                   └────────────┘ ◀── result cache ─── └──────┬───────┘
                          │                                    │
                          ▼                                    ▼
                   ┌─────────────────────────────────────────────┐
                   │              PostgreSQL                     │
                   │              attack_logs                    │
                   └─────────────────────────────────────────────┘
```

### Streams

| Stream             | Producer       | Consumer        | Payload                    |
| ------------------ | -------------- | --------------- | -------------------------- |
| `packet_ingest`    | ingestion      | flow_builder    | `PacketEvent`              |
| `flow_inference`   | flow_builder   | inference       | `FlowFeatureEvent`         |
| `predict_jobs`     | api            | inference       | `PredictJob`               |

Inference also writes a per-job result under the Redis key
`predict_results:<job_id>` with a configurable TTL
(`PREDICT_RESULT_TTL_SECONDS`, default 1 hour). The API polls this key.

## Async prediction flow

1. Client `POST /api/v1/predict` with a 39-feature vector + JWT.
2. API validates with pydantic, generates `job_id`, publishes a `PredictJob`
   onto `predict_jobs`, and returns `202 {job_id, poll_url}` immediately.
3. The inference worker consumes the job, runs the classifier, persists an
   `AttackLog` row, and stores `PredictJobResult` in Redis.
4. Client `GET /api/v1/predict/<job_id>` returns the cached result, or 404
   when the TTL has expired (the alert remains queryable via `/alerts`).

This decouples HTTP latency from inference latency. A 5 s model run no
longer blocks a Gunicorn worker.

## Auth

JWT-based, issued by `POST /api/v1/auth/token` against admin bootstrap
credentials. The settings layer **fails fast** at startup if any of
`SECRET_KEY`, `JWT_SECRET_KEY`, or `ADMIN_PASSWORD` are still at their
`change-me-in-production` placeholder values when `ENVIRONMENT` is not
`development` or `test`. Use `make bootstrap` to generate safe random
credentials in `.env`.

## Data persistence

- Schema is owned by `shared/db/models.py` and managed by Alembic
  (`shared/db/migrations/`).
- Every service uses `shared.db.session_scope()`. Flask is **not** the owner
  of the engine; workers use the same code path as routes.
- The first compose run executes the `migrations` service, which runs
  `alembic upgrade head` against the database before the API or workers
  start.

## Observability

- Structured JSON logging (`shared.observability.logging`).
- A `correlation_id` contextvar is bound at every entry point (HTTP request,
  broker message, predict job) so a single id flows through all four
  services.
- `GET /api/v1/health` is a liveness probe.
- `GET /api/v1/ready` performs a `SELECT 1` against the database.

## Known issues / open audit findings

### Q1 — Upstream `URG`-vs-`PSH` bug in `flow/Flow.py`

`Flow.__init__` and `Flow.new` set `setFwdPSHFlags` from `getURGFlag` rather
than `getPSHFlag`. The behavior is inherited from upstream and the currently
shipped `models/model.pkl` was trained against this buggy feature, so
"fixing" the bug without retraining would silently degrade accuracy.

**Decision (per audit approval):** retain the bug, mark with
`# TODO(model-retrain)` comments, and fix when the model is retrained.

### Q2 — Stub fallback classifier

`ALLOW_FALLBACK_CLASSIFIER` defaults to `false`. When set to `true`, a
deterministic stub classifier replaces the real model when artifacts are
missing. Intended for local development and CI **only**.

### Q3 — Autoencoder + LIME explainer

Both artifacts are loaded by `ModelService` but the inference path doesn't
currently use them. They will be wired into the explanations endpoint in a
future iteration; until then they're inert.

## Future work

- Replace the bootstrap admin user with a real user table + invitations.
- Add a frontend (separate repo) consuming `/alerts` over WebSocket/SSE.
- Implement a real model registry and switch `ALLOW_FALLBACK_CLASSIFIER`'s
  semantics from "hidden stub" to "explicit registry pull".
- Add Prometheus metrics on the broker (`xpending`, lag) and the API
  (request histograms).
