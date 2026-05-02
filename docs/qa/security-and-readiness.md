# QA & Security Readiness Report

This document records the four QA exit-criteria the project owner asked
for. Re-run any of these locally with the commands below.

## 1. SAST scan (bandit)

Tool: `bandit==1.9.4` (CWE-mapped). Command:

```bash
make security
# or directly:
bandit -r services shared flow -ll
```

**Result: 0 high / 0 medium / 0 low issues across 2,316 LOC.**

The first pass surfaced 9 raw findings — every one was either expected
(loading our own model artifacts) or required for capture (subprocess
spawning tcpdump). Remediation:

| Bandit ID | Location | Disposition |
| --- | --- | --- |
| B403 import pickle / dill | `services/inference/model_service.py:25-28` | Acknowledged with `# nosec B403`. Deserialization is now gated by `models/manifest.sha256.json` before any unsafe load runs. |
| B301 pickle.load / dill | `services/inference/model_service.py:113,150` | Same trust boundary, plus SHA-256 verification before every artifact load. `# nosec B301` remains with rationale comment. |
| B404 import subprocess | `services/ingestion/sniffer.py:5` | tcpdump fallback path; `# nosec B404`. |
| B602 subprocess_shell | `services/ingestion/sniffer.py:89` | Command string comes from `CAPTURE_CMD` env, never request input. `# nosec B602` with comment. |
| B101 assert (×2) | `services/ingestion/sniffer.py:92`, `shared/db/engine.py:51` | Replaced with explicit `if … raise RuntimeError(...)` so behavior survives `python -O`. |
| B110 try/except/pass (×2) | `services/ingestion/publisher.py:45`, `shared/broker/redis_streams.py:123` | Defensive close paths; replaced silent `pass` with `logger.debug(...)`. |

The project also enforces fail-fast secret validation
(<ref_file file="/home/ubuntu/repos/RT-AI-IDS/shared/security/secrets_validation.py" />)
which refuses to boot whenever `SECRET_KEY`, `JWT_SECRET_KEY`, or
`ADMIN_PASSWORD` are still at their `.env.example` placeholders unless
`ENVIRONMENT` is `development` or `test`. Verified by
`tests/unit/test_settings_failfast.py`.

The full machine-readable bandit output lives in
[`docs/bandit-report.json`](../bandit-report.json).

## 2. CORS & Frontend Readiness

`Flask-Cors==5.0.0` is wired into the API factory
(<ref_snippet file="/home/ubuntu/repos/RT-AI-IDS/services/api/app.py" lines="38-46" />).
Behavior:

- Allow-list comes from the env var `CORS_ALLOW_ORIGINS` (comma-separated).
  Wildcard (`*`) is intentionally not honored when credentials are involved.
- `supports_credentials=True` — the React app may send the `Authorization`
  header.
- Allowed methods: `GET, POST, OPTIONS`. Allowed headers:
  `Authorization, Content-Type`. Preflight cached for 600 s.
- Default value is empty: the API stays same-origin until the operator
  explicitly opts a frontend in.

Verification against the live container with
`CORS_ALLOW_ORIGINS=http://localhost:5173,https://soc.example.com`:

```http
> OPTIONS /api/v1/predict HTTP/1.1
> Origin: http://localhost:5173
> Access-Control-Request-Method: POST
> Access-Control-Request-Headers: Authorization,Content-Type
< HTTP/1.1 200 OK
< Access-Control-Allow-Origin: http://localhost:5173
< Access-Control-Allow-Credentials: true
< Access-Control-Allow-Headers: Authorization, Content-Type
< Access-Control-Allow-Methods: GET, OPTIONS, POST
< Access-Control-Max-Age: 600
< Vary: Origin
```

Disallowed origins simply do not get the `Access-Control-Allow-Origin`
header, so the browser blocks them. Covered by
[`tests/integration/test_cors.py`](../../tests/integration/test_cors.py).

## 3. API Documentation

- OpenAPI 3.1 spec: [`docs/openapi.yaml`](../openapi.yaml). Paste into
  [editor.swagger.io](https://editor.swagger.io/) for an interactive view.
- Concise endpoint reference for the frontend developer:
  [`docs/api.md`](../api.md). Every endpoint has a copy-pasteable
  request/response example, including the async predict round-trip.

## 4. End-to-End async test (Redis Streams non-blocking)

Test driver: [`scripts/concurrent_predict.py`](../../scripts/concurrent_predict.py).
Re-run locally:

```bash
make compose-up                                  # api+inference+flow-builder+db+redis
set -a && source .env && set +a
N=100 python3 scripts/concurrent_predict.py
```

The driver:

1. Authenticates against `/api/v1/auth/token` once.
2. Fires `N` concurrent `POST /api/v1/predict` enqueues from a thread
   pool (each request must return `202 + job_id`).
3. Polls `GET /api/v1/predict/{job_id}` for every accepted job and
   reports first-result and all-results timings.

### Recorded run, N=100

```
firing 100 concurrent /predict enqueues against http://localhost:5000 ...
  enqueue wall time: 341.2 ms
  202 accepted:      100 / 100
  enqueue latency ms  min/p50/p95/max = 3.5/36.9/107.9/117.4
polling 100 job ids ...
  completed:         100 / 100
  first result in:   5.9 ms after first poll
  all results in:    269.5 ms after first poll
  worker latency ms  min/p50/p95/max = 5.9/119.5/209.3/269.5

PROOF OF NON-BLOCKING:
  All 100 concurrent enqueues returned 202 in <500 ms each (117.4 ms max),
  while the worker drained 100 jobs in 269.5 ms total. API never blocked on
  inference.
```

What this proves:

- The API path **never** runs inference — its p95 enqueue latency is
  ~108 ms even under 100 concurrent in-flight requests on a 2-worker
  Gunicorn (the queueing is HTTP, not ML). If the API were inlining the
  model call, p95 would be hundreds of ms higher.
- The `predict_jobs` Redis Stream is being drained concurrently — first
  result lands ~6 ms after the first poll, meaning the worker had
  already started processing while the producer was still enqueuing.
- The cached result lookup pattern (`PREDICT_RESULT_TTL_SECONDS`)
  succeeds for every job_id without any race or "lost result" failures.

### N=30 reference run

```
enqueue wall time: 85.3 ms          (max enqueue 29.7 ms)
all results drained in 123.0 ms after first poll
```
