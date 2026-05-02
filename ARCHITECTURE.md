# RT-AI-IDS Architecture and Operations

## 1) Project Overview

**RT-AI-IDS (Real-Time AI Intrusion Detection System)** is an asynchronous, microservices-based network intrusion detection platform that captures packets, converts them to flow features, classifies them with ML inference, and serves alerts via a REST API.

Core stack:

- **Packet capture:** Scapy (with native/tcpdump capture options)
- **Message transport:** Redis Streams + Redis key-value cache
- **Backend API:** Flask, JWT auth, Pydantic validation
- **Workers:** Python services for ingestion, flow building, and inference
- **Persistence:** PostgreSQL + SQLAlchemy 2.x + Alembic migrations
- **ML/XAI:** scikit-learn/TensorFlow artifacts with LIME background explanation hooks
- **Operations:** Docker Compose, per-service Dockerfiles, Makefile workflows

---

## 2) Directory Structure (ASCII Tree)

```text
RT-AI-IDS-main/
├── application.py
├── docker-compose.yml
├── Makefile
├── .env.example
├── requirements.txt
├── pyproject.toml
├── ARCHITECTURE.md
├── README.md
├── services/
│   ├── api/
│   │   ├── app.py
│   │   ├── cli.py
│   │   ├── deps.py
│   │   ├── error_handlers.py
│   │   ├── extensions.py
│   │   ├── jwt_denylist.py
│   │   ├── responses.py
│   │   ├── retention.py
│   │   ├── routes/
│   │   │   ├── auth.py
│   │   │   ├── health.py
│   │   │   ├── predict.py
│   │   │   ├── alerts.py
│   │   │   └── stats.py
│   │   └── schemas/
│   │       ├── auth.py
│   │       ├── predict.py
│   │       └── alerts.py
│   ├── ingestion/
│   │   ├── run_sniffer.py
│   │   ├── sniffer.py
│   │   └── publisher.py
│   ├── flow_builder/
│   │   ├── service.py
│   │   └── worker.py
│   └── inference/
│       ├── worker.py
│       ├── service.py
│       ├── model_service.py
│       ├── model_loader.py
│       ├── repository.py
│       ├── wireless_rules.py
│       └── xai.py
├── shared/
│   ├── broker/
│   │   ├── base.py
│   │   ├── redis_streams.py
│   │   └── retry.py
│   ├── config/
│   │   └── settings.py
│   ├── db/
│   │   ├── engine.py
│   │   ├── models.py
│   │   └── migrations/
│   │       ├── env.py
│   │       └── versions/
│   │           ├── 0001_initial.py
│   │           ├── 0002_attack_logs_model_metadata.py
│   │           └── 0003_attack_log_query_indexes.py
│   ├── observability/
│   │   └── logging.py
│   ├── schemas/
│   │   ├── events.py
│   │   └── jobs.py
│   └── security/
│       └── secrets_validation.py
├── flow/
│   ├── Flow.py
│   ├── FlowFeature.py
│   └── PacketInfo.py
├── infra/
│   ├── docker/
│   │   ├── api.Dockerfile
│   │   ├── flow_builder.Dockerfile
│   │   ├── inference.Dockerfile
│   │   ├── ingestion.Dockerfile
│   │   └── nginx.Dockerfile
│   └── nginx/
│       ├── default.conf
│       └── entrypoint.sh
├── models/
│   ├── model.pkl
│   ├── manifest.sha256.json
│   └── README.md
├── docs/
│   ├── openapi.yaml
│   ├── api.md
│   ├── architecture.md
│   ├── operations.md
│   ├── live-demo-setup.md
│   ├── threat-model.md
│   └── qa/security-and-readiness.md
├── scripts/
│   └── concurrent_predict.py
└── tests/
    ├── conftest.py
    ├── integration/
    └── unit/
```

---

## 3) Component Breakdown

### `services/api`

- Hosts the Flask application and registers all REST routes.
- Handles authentication (`/api/v1/auth/token`, logout revoke), health checks, async predict enqueue/poll, alert listing, and stats aggregation.
- Uses shared broker and DB modules; emits consistent JSON error envelope format.
- Validates request/response models with Pydantic schemas.

### `services/ingestion`

- Captures packets from configured interface or alternative capture source.
- Converts captured traffic to normalized packet events and publishes to Redis Stream (`INGEST_STREAM`, default `packet_ingest`).
- Runs as dedicated capture service (`python -m services.ingestion.run_sniffer`).

### `services/flow_builder`

- Consumes packet events from Redis.
- Aggregates packets into flow state and emits fixed-length feature vectors (39 features) for terminated or timed-out flows.
- Publishes features to `FLOW_INFERENCE_STREAM` (default `flow_inference`).

### `services/inference`

- Consumes both `flow_inference` events and API `predict_jobs`.
- Loads model artifacts once per process (`ModelService`) with SHA-256 manifest verification (`model_loader.py`).
- Performs classification, computes risk label/score, writes alerts to PostgreSQL, and stores async poll results in Redis key-value (`predict_results:<job_id>`).
- Includes best-effort LIME background explanation hooks (`xai.py`).

### `shared/broker`

- Defines broker interface (`base.py`) and Redis Streams implementation (`redis_streams.py`).
- Supports publish/consume/ack, bounded stream length (`BROKER_MAX_STREAM_LEN`), retry handling, and DLQ support.
- Stores and retrieves async prediction results via Redis keys with typed load outcomes.

### `shared/db`

- Central SQLAlchemy engine/session management (`engine.py`).
- `AttackLog` ORM model (`models.py`) represents persisted detections with model metadata.
- Alembic migrations maintain schema and indexes in a versioned, reproducible way.

### `shared/config`

- Environment-driven runtime settings (`settings.py`).
- Enforces fail-fast secret validation in non-development environments.
- Provides all stream names, broker limits, auth limits, DB pool settings, retention, and model metadata settings.

### `docs`

- Contains OpenAPI contract (`docs/openapi.yaml`), API usage guide, architecture notes, operations runbook, and security/threat-model material.

### `tests`

- Integration tests for API behavior and auth/predict/alerts flows.
- Unit tests for broker, inference logic, model integrity, config posture, retention, and capture logic.

---

## 4) Data Flow Pipeline (Scapy -> Redis -> AI -> PostgreSQL -> API)

1. **Packet capture (Scapy):** `services/ingestion` captures live traffic from `CAPTURE_INTERFACE` and builds packet event payloads.
2. **Ingress queue (Redis Streams):** Packet events are appended to `INGEST_STREAM` (`packet_ingest`).
3. **Flow construction:** `services/flow_builder/worker.py` consumes packet events, maintains flow state, and emits completed flow feature events.
4. **Inference queue:** Flow feature events are appended to `FLOW_INFERENCE_STREAM` (`flow_inference`).
5. **AI inference:** `services/inference/worker.py` consumes flow features, runs model prediction, maps risk, and enriches rationale.
6. **Persistence:** `services/inference/repository.py` writes classified detections into PostgreSQL table `attack_logs`.
7. **API serving:** `services/api/routes/alerts.py` queries `attack_logs` and returns JSON arrays/objects from `/api/v1/alerts` and `/api/v1/alerts/{id}`.
8. **Async predict path:** API `POST /api/v1/predict` writes a pending result key and enqueues `predict_jobs`; inference worker writes completion/failure back to `predict_results:<job_id>`; API poll endpoint returns pending/completed/failed states.

---

## 5) How to Run (Exact Commands)

## Docker-first startup

```bash
# 1) Create environment file
cp .env.example .env

# 2) Build and start all core services
docker compose up --build -d

# 3) Confirm service status
docker compose ps

# 4) Follow logs
docker compose logs -f --tail=200
```

## Optional: start ingestion profile for live capture (Linux host network mode)

```bash
docker compose --profile capture up -d ingestion
docker compose logs -f ingestion
```

## Stop stack

```bash
docker compose down -v
```

## Makefile equivalents

```bash
make compose-up
make compose-logs
make compose-down
```

## Local Python workflows (development/QA)

```bash
make install
make lint
make typecheck
make test
make security
```

---

## Notes for Frontend Integration

- Primary endpoints: `/api/v1/auth/token`, `/api/v1/predict`, `/api/v1/predict/{job_id}`, `/api/v1/alerts`, `/api/v1/stats`.
- API contract source of truth: `docs/openapi.yaml`.
- Async UX requirement: client should treat `POST /predict` as enqueue-only and poll `GET /predict/{job_id}` until non-pending status.
