# Production-Grade Asynchronous IDS

This project is a modular, microservice-oriented Intrusion Detection System (IDS) that
supports real-time packet ingestion, flow feature extraction, ML-based inference, and alert
persistence/query through a JWT-protected REST API.

## Project Overview

```mermaid
flowchart LR
  packetSources[PacketSources] --> ingestSvc[IngestionService]
  ingestSvc --> redisBroker[RedisBroker]
  redisBroker --> flowSvc[FlowBuilderWorker]
  flowSvc --> redisBroker
  redisBroker --> inferSvc[InferenceWorker]
  inferSvc --> postgresDb[PostgresAttackLogDB]
  apiSvc[FlaskApiService] --> postgresDb
  apiSvc --> clients[FrontendOrSIEM]
```

### Service Responsibilities

- `services/ingestion`
  - Captures packets from live interfaces, PCAP replay, or tcpdump JSON streams.
  - Publishes normalized packet events to Redis.
- `services/flow_builder`
  - Aggregates packets into flows and computes feature vectors.
  - Applies stale-flow cleanup and bounded in-memory flow tracking.
  - Pushes finalized flow feature events to inference queue.
- `services/inference`
  - Loads ML artifacts once and keeps them resident in memory per worker.
  - Produces classifications, risk scores, and defensive wireless findings.
  - Persists alerts to the database.
- `services/api`
  - Exposes health, auth, prediction, alerts, and stats endpoints.
  - Requires JWT for protected endpoints.
- `shared`
  - Centralized settings and schema contracts shared across services.

## Defensive Detection Methodology

- Wireshark/tshark-compatible and `tcpdump`-driven packet workflows.
- Defensive wireless analytics:
  - suspicious 802.11 management-frame burst detection
  - deauthentication flood indicators
  - WEP/WPS risk posture indicators
- TLS metadata-first strategy for encrypted traffic. Full payload decryption must only be used
  in explicitly authorized and compliant environments.

## Prerequisites

- Python 3.11+
- Docker and Docker Compose (for containerized deployment)
- Redis and PostgreSQL (if running without Docker)
- Packet capture permissions (Npcap/WinPcap equivalent on Windows)

## Local Setup (Without Docker)

1. Create a virtual environment:
   - `python -m venv .venv`
2. Activate the environment:
   - PowerShell: `.venv\\Scripts\\Activate.ps1`
3. Install dependencies:
   - `pip install -r requirements.txt`
4. Configure environment variables (example):
   - `SECRET_KEY=replace-me`
   - `JWT_SECRET_KEY=replace-me`
   - `ADMIN_USERNAME=admin`
   - `ADMIN_PASSWORD=change-me`
   - `LOG_LEVEL=INFO`
   - `DATABASE_URL=postgresql+psycopg2://ids:ids@localhost:5432/ids`
   - `REDIS_URL=redis://localhost:6379/0`

## Run Services Locally

Run each service in a separate terminal:

1. API:
   - `python application.py`
2. Flow builder worker:
   - `python -m services.flow_builder.worker`
3. Inference worker:
   - `python -m services.inference.worker`
4. Ingestion service (live interface):
   - `python -m services.ingestion.run_sniffer --interface <iface>`
5. Ingestion service (PCAP replay):
   - `python -m services.ingestion.run_sniffer --pcap-file sample.pcap`

## Docker Deployment

- Start all services:
  - `docker compose up --build`
- Start with packet capture container enabled:
  - `docker compose --profile capture up --build`
- Stop:
  - `docker compose down`

Default database provisioning in Compose:
- host: `localhost`
- port: `5432`
- db: `ids`
- user: `ids`
- password: `ids`

## API Documentation

Base URL: `http://localhost:5000`

### Health Endpoints

- `GET /api/v1/health`
- `GET /api/v1/ready`

### Auth Endpoint

- `POST /api/v1/auth/token`
- Credentials are controlled via env vars `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

Request:
```json
{
  "username": "admin",
  "password": "admin"
}
```

Response:
```json
{
  "access_token": "<jwt>"
}
```

### Predict Endpoint (JWT Required)

- `POST /api/v1/predict`

Headers:
- `Authorization: Bearer <jwt>`

Request:
```json
{
  "flow_id": "optional-flow-id",
  "features": [0.1, 0.2, 0.3, "... total 39 values ..."],
  "context": {
    "src_ip": "10.0.0.1",
    "src_port": 5151,
    "dst_ip": "10.0.0.2",
    "dst_port": 443,
    "protocol": "TCP",
    "wireless": {
      "link_type": "wifi",
      "privacy_wep_enabled": true,
      "wps_enabled": true,
      "wps_failed_enrollment_attempts": 4
    }
  }
}
```

Response:
```json
{
  "id": 1,
  "flow_id": "optional-flow-id",
  "source_ip": "10.0.0.1",
  "source_port": 5151,
  "destination_ip": "10.0.0.2",
  "destination_port": 443,
  "protocol": "TCP",
  "classification": "Suspicious",
  "probability": 0.6,
  "risk_label": "medium",
  "risk_score": 0.6,
  "rationale": [
    "legacy_wep_exposure_indicator",
    "wps_exposure_or_bruteforce_indicator",
    "ml_model_flagged_flow"
  ],
  "created_at": "2026-01-01T00:00:00+00:00"
}
```

### Alerts Endpoints (JWT Required)

- `GET /api/v1/alerts?limit=50`
- `GET /api/v1/alerts/<id>`

### Stats Endpoint

- `GET /api/v1/stats` (JWT required)

## Testing

- Run unit and integration tests:
  - `python -m pytest -q`

Covered test areas:
- inference model lifecycle and rationale generation
- wireless rule behavior
- flow builder memory/termination behavior
- API health/auth/predict/alerts workflow

## Front-End Integration Guide (React Example)

1. Authenticate once and store JWT in memory or secure storage.
2. Call `POST /api/v1/predict` for manual/simulated analysis requests.
3. Poll `GET /api/v1/alerts` for near-real-time dashboard updates.
4. Visualize alert severity using `risk_label` and `risk_score`.

Example fetch call:
```javascript
const token = "<jwt>";
const res = await fetch("http://localhost:5000/api/v1/alerts?limit=25", {
  headers: { Authorization: `Bearer ${token}` }
});
const alerts = await res.json();
```

## Production Notes

- Replace bootstrap credentials with a real identity provider.
- Rotate secrets and disable default values in production.
- Add transport security, centralized logging, and metrics dashboards.
- Consider schema migrations (Alembic) before multi-environment rollout.
- For containerized packet capture, set `CAPTURE_INTERFACE` and run with
  `--profile capture`.

