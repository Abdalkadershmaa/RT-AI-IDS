# Operations Guide

## Local development

```bash
git clone https://github.com/Abdalkadershmaa/RT-AI-IDS.git
cd RT-AI-IDS
make bootstrap            # generate .env with random secrets
docker compose up --build # api, db, redis, flow_builder, inference, migrations
```

API is exposed on `http://localhost:5000` once the `api` container reports
healthy. Hit `GET /api/v1/health` and `GET /api/v1/ready` to verify.

## Generating a JWT

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/v1/auth/token \
  -H 'Content-Type: application/json' \
  -d "{\"username\": \"$ADMIN_USERNAME\", \"password\": \"$ADMIN_PASSWORD\"}" \
  | jq -r .access_token)
```

## Submitting an async prediction

```bash
JOB=$(curl -s -X POST http://localhost:5000/api/v1/predict \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"features": [0.1] * 39, "context": {"src_ip": "10.0.0.1"}}' \
  | jq -r .job_id)

# Poll the result
curl -s "http://localhost:5000/api/v1/predict/$JOB" \
  -H "Authorization: Bearer $TOKEN" | jq
```

## Inspecting the streams

```bash
docker compose exec redis redis-cli XINFO STREAM packet_ingest
docker compose exec redis redis-cli XINFO STREAM flow_inference
docker compose exec redis redis-cli XINFO STREAM predict_jobs
docker compose exec redis redis-cli XPENDING flow_inference rt_ai_ids
```

## Capturing live traffic

The `ingestion` service is gated behind a Compose profile so the rest of the
stack runs cleanly without root privileges:

```bash
CAPTURE_INTERFACE=eth0 docker compose --profile capture up -d ingestion
```

The ingestion container needs `NET_RAW` and `NET_ADMIN` capabilities, which
the compose file already grants.

## Runbook: services not starting

1. Check healthchecks: `docker compose ps`.
2. Check logs: `docker compose logs -f api flow-builder inference`.
3. If the API logs `InsecureDefaultSecretError`, you forgot `make bootstrap`
   or are running with `ENVIRONMENT=production` and placeholder secrets.
4. If the inference worker logs `ModelArtifactError`, either populate the
   `models/` directory with the LFS-tracked artifacts, or set
   `ALLOW_FALLBACK_CLASSIFIER=true` in `.env` for local-only testing.

## Migrations

```bash
make migrate                                                    # upgrade head
docker compose run --rm migrations python -m alembic -c shared/db/migrations/alembic.ini current
```

To create a new migration:

```bash
docker compose run --rm migrations python -m alembic \
  -c shared/db/migrations/alembic.ini revision --autogenerate -m "your message"
```
