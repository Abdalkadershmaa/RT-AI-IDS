# RT-AI-IDS API Reference

Base URL: `http://localhost:5000` (for local docker-compose).
All non-public endpoints require a JWT bearer token: `Authorization: Bearer <token>`.

The OpenAPI 3.1 spec is the source of truth: [`docs/openapi.yaml`](./openapi.yaml).
Render it interactively with [Swagger UI](https://editor.swagger.io/) by pasting
the file contents.

## Authentication

### `POST /api/v1/auth/token`

Issue a JWT.

```bash
curl -s -X POST http://localhost:5000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<from-.env>"}'
```

**200 OK**
```json
{ "access_token": "eyJ...", "token_type": "bearer", "expires_in": 86400 }
```

Errors: `400 invalid_request`, `401 unauthorized`.

## Async predict round-trip

The frontend integration looks like:

```
React  ───POST /api/v1/predict──▶ API  ───XADD predict_jobs──▶ Redis
                ◀──202 {job_id}──                                    │
                                                                     ▼
React  ───GET /api/v1/predict/<id>─▶ API  ◀──XACK + cached result── Inference worker
                ◀── completed ───
```

### `POST /api/v1/predict`

Enqueue an inference job. The API does **not** run the model; it returns
immediately so it can keep serving HTTP.

Request body (must contain exactly 39 finite floats):

```json
{
  "flow_id": "client-supplied-or-omitted",
  "features": [1.0, 2.0, ..., 39.0],
  "context": {
    "source_ip": "10.0.0.1",
    "source_port": 1234,
    "destination_ip": "10.0.0.2",
    "destination_port": 80,
    "protocol": "TCP"
  }
}
```

The canonical context field names are `source_ip` / `source_port` /
`destination_ip` / `destination_port` — same shape as the alert response so
client code can reuse a single model. The legacy short forms (`src_ip`,
`src_port`, `dst_ip`, `dst_port`) are still accepted for backward
compatibility with internal flow-pipeline events but are deprecated for new
clients.

**202 Accepted**
```json
{
  "job_id": "fa84367c1e994a8c9fe0fc5bb72c3e94",
  "status": "pending",
  "poll_url": "/api/v1/predict/fa84367c1e994a8c9fe0fc5bb72c3e94"
}
```

Errors: `400 invalid_request` (NaN/Inf, wrong length, extra fields),
`401 unauthorized`.

### `GET /api/v1/predict/{job_id}`

Poll once or with light backoff (e.g. every 250 ms). Results are cached in
Redis with `PREDICT_RESULT_TTL_SECONDS` (default 1 h).

**200 OK** (completed)
```json
{
  "job_id": "fa84367c1e994a8c9fe0fc5bb72c3e94",
  "status": "completed",
  "flow_id": "client-supplied-or-omitted",
  "classification": "Suspicious",
  "probability": 0.98,
  "risk_label": "minimal",
  "risk_score": 0.02,
  "rationale": ["ml_model_flagged_flow"],
  "alert_id": 3,
  "completed_at": "2026-04-26T08:56:25.116230+00:00",
  "error": null
}
```

**200 OK** (still processing) — only `job_id` and `status: "pending"`
fields are guaranteed populated.

**404 Not Found** — job id never existed or its TTL expired.

## Alerts & stats

### `GET /api/v1/alerts`

Query params:
- `limit` (1–500, default 50)
- `risk_label` (exact match)

**200 OK** — array of [`Alert`](./openapi.yaml). Most recent first.

### `GET /api/v1/stats`

**200 OK**
```json
{
  "total_alerts": 42,
  "risk_distribution": { "minimal": 30, "high": 10, "critical": 2 }
}
```

## Health

### `GET /api/v1/health`

Liveness — always 200 when the process is up. Used by the docker
healthcheck.

### `GET /api/v1/ready`

Readiness — 200 only when the database is reachable. Use this from
Kubernetes / load balancers, not `/health`.

## Errors

All error responses follow:

```json
{ "error": "stable_machine_code", "detail": "human-readable or pydantic report" }
```

Common codes:

| HTTP | code              | meaning                                  |
| ---- | ----------------- | ---------------------------------------- |
| 400  | `invalid_request` | pydantic rejection, malformed JSON       |
| 401  | `unauthorized`    | missing/invalid/expired JWT              |
| 404  | `not_found`       | unknown job id, unknown alert id         |
| 413  | `payload_too_large` | body > 1 MiB                           |
| 500  | `internal_error`  | unexpected exception (logged with cid)   |

## CORS

Set `CORS_ALLOW_ORIGINS=http://localhost:5173,https://soc.example.com`
(comma-separated) and restart the API container. The server will respond
with `Access-Control-Allow-Origin` only for those exact origins.
Credentials (Authorization header) are supported. Wildcard (`*`) is
intentionally not honored.

## Observability

Every API request and broker message gets a `correlation_id` (UUID-hex)
that flows through structured JSON logs. Prefer:

```bash
docker compose logs api inference flow-builder | jq 'select(.correlation_id == "<id>")'
```
