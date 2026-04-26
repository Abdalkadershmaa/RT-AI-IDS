# RT-AI-IDS — Real-Time AI Intrusion Detection System

Asynchronous, microservices-based IDS that captures network packets,
aggregates them into bidirectional flows, classifies each flow with a
machine-learning model, and persists alerts for query through a JWT-protected
HTTP API.

## Services

| Service        | Role                                                                                | Entrypoint                                  |
| -------------- | ----------------------------------------------------------------------------------- | ------------------------------------------- |
| `api`          | Flask + JWT REST API; enqueues async predict jobs; serves `/alerts`, `/stats`       | `gunicorn application:app`                  |
| `ingestion`    | Async packet capture (Scapy / PCAP / tcpdump JSON); publishes to `packet_ingest`    | `python -m services.ingestion.run_sniffer`  |
| `flow_builder` | Stateful aggregator — packets → flow features; publishes to `flow_inference`        | `python -m services.flow_builder.worker`    |
| `inference`    | Loads ML artifacts once per process; consumes `flow_inference` + `predict_jobs`     | `python -m services.inference.worker`       |

Communication is over **Redis Streams** with consumer groups. PostgreSQL
(SQLAlchemy + Alembic) persists every alert. See
[docs/architecture.md](docs/architecture.md) for the full picture.

## Layout

```
.
├── application.py              # Flask entrypoint (Gunicorn imports this)
├── services/
│   ├── api/                    # Flask app, blueprints, schemas, error handlers
│   ├── ingestion/              # Capture adapters + async publisher
│   ├── flow_builder/           # Flow aggregation worker
│   └── inference/              # ML loader, classifier, persistence
├── shared/
│   ├── broker/                 # Redis Streams abstraction
│   ├── config/                 # pydantic-style settings + fail-fast
│   ├── db/                     # SQLAlchemy engine, ORM, Alembic migrations
│   ├── observability/          # Structured JSON logging + correlation IDs
│   ├── schemas/                # Cross-service event/job dataclasses
│   └── security/               # Secret validation, etc.
├── flow/                       # Legacy CICFlowMeter-derived feature extractor
├── infra/
│   └── docker/                 # Per-service Dockerfiles
├── requirements/               # Per-service requirements files
├── models/                     # ML artifacts (Git LFS)
├── docs/                       # architecture / operations / threat-model
└── tests/                      # unit + integration
```

## Quickstart

```bash
make bootstrap                  # generate .env with random secrets
docker compose up --build       # api, db, redis, flow_builder, inference, migrations
```

The API will be available on `http://localhost:5000`. Healthcheck:
`GET /api/v1/health`.

## API surface (v1)

| Method | Path                          | Auth | Description                                       |
| ------ | ----------------------------- | ---- | ------------------------------------------------- |
| GET    | `/api/v1/health`              | —    | Liveness probe                                    |
| GET    | `/api/v1/ready`               | —    | Readiness probe (DB connectivity)                 |
| POST   | `/api/v1/auth/token`          | —    | Exchange admin creds for a JWT                    |
| POST   | `/api/v1/predict`             | JWT  | Enqueue prediction → 202 + `job_id`               |
| GET    | `/api/v1/predict/<job_id>`    | JWT  | Poll cached prediction result                     |
| GET    | `/api/v1/alerts`              | JWT  | List alerts (`?limit=`)                           |
| GET    | `/api/v1/alerts/<id>`         | JWT  | Fetch one alert                                   |
| GET    | `/api/v1/stats`               | JWT  | Total alerts + risk distribution                  |

Examples in [docs/operations.md](docs/operations.md).

## Development

```bash
make install                    # runtime + dev dependencies
make lint                       # ruff
make test                       # pytest
```

Pre-commit hooks: `pre-commit install` after the first `make install`.

## Environment configuration

See [`.env.example`](.env.example). The settings layer **refuses to start**
when `ENVIRONMENT` is not `development`/`test` and any of `SECRET_KEY`,
`JWT_SECRET_KEY`, or `ADMIN_PASSWORD` are still at their `change-me-…`
placeholders.

## Live capture

The `ingestion` service is gated behind a Compose profile because it needs
`NET_RAW` / `NET_ADMIN`:

```bash
make list-interfaces                                        # find your NIC name
echo "CAPTURE_INTERFACE=wlan0" >> .env                      # or whatever it is
docker compose --profile capture up -d ingestion            # Linux
# Windows / macOS: see docs/live-demo-setup.md (run ingestion natively)
```

Promiscuous mode is **enabled by default** so the sniffer sees traffic
between other hosts on the same L2 segment (i.e. attacker → victim
flowing through your laptop's hotspot NIC). Toggle with
`CAPTURE_PROMISCUOUS=false` if your network policy forbids it.

For the full demo-day walkthrough — finding the right interface on
Linux/Windows/macOS, attacker setup, Nmap and DoS scripts, troubleshooting
— see [docs/live-demo-setup.md](docs/live-demo-setup.md).

## License

Same as upstream — see `LICENSE` (if present).
