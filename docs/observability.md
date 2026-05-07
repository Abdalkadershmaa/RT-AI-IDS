# Observability

RT-AI-IDS ships with three independent observability layers. All three are
**optional at runtime** — the application keeps working when the backing
libraries (`prometheus_client`, the OpenTelemetry SDK) aren't installed.
This is deliberate: the slim CI test image and constrained edge deployments
don't pay for telemetry they won't consume, while production deployments
get the full pipeline.

| Layer        | Module                            | Optional dependency               |
|--------------|-----------------------------------|-----------------------------------|
| Logging      | `shared.observability.logging`    | none (stdlib only)                |
| Metrics      | `shared.observability.metrics`    | `prometheus-client`               |
| Tracing      | `shared.observability.tracing`    | `opentelemetry-sdk` + exporter    |

---

## 1. Structured logging (SOC SIEM schema)

Every log line is one JSON object on stdout. Splunk / Elastic / Datadog can
parse it without a custom grok pattern. The schema is **versioned** so
parsers can pin against a known shape.

### Required keys

| Key              | Type    | Notes                                              |
|------------------|---------|----------------------------------------------------|
| `ts`             | string  | ISO-8601 UTC, millisecond precision                |
| `schema_version` | string  | Bumped on breaking field changes (`LOG_SCHEMA_VERSION`) |
| `service`        | string  | `rt-ai-ids-api`, `rt-ai-ids-inference`, …          |
| `level`          | string  | Python log level name                              |
| `logger`         | string  | Python logger name                                 |
| `event`          | string  | Short snake_case event name                        |
| `message`        | string  | Human-readable message                             |

### Conditional keys

| Key              | When                                                  |
|------------------|-------------------------------------------------------|
| `correlation_id` | A correlation id is bound via `bind_correlation_id()` |
| `trace_id`       | An OTel span is active                                |
| `span_id`        | An OTel span is active                                |
| `exc_info`       | The log call passed an exception                      |

### Example record

```json
{
  "ts": "2026-04-26T07:21:55.012+00:00",
  "schema_version": "1.0",
  "service": "rt-ai-ids-api",
  "level": "INFO",
  "logger": "services.api.routes.predict",
  "event": "predict_job_enqueued",
  "message": "predict_job_enqueued",
  "correlation_id": "abc123",
  "trace_id": "0af7651916cd43dd8448eb211c80319c",
  "span_id": "b7ad6b7169203331",
  "job_id": "abc123",
  "flow_id": "flow-1"
}
```

### Configuration

| Env var              | Default            | Purpose                          |
|----------------------|--------------------|----------------------------------|
| `LOG_LEVEL`          | `INFO`             | Root logger level                |
| `LOG_SCHEMA_VERSION` | `1.0`              | Pinned SIEM schema version       |
| `SERVICE_NAME`       | `rt-ai-ids-api`    | Default `service` field          |

---

## 2. Prometheus metrics

Exporter mounted at **`GET /api/v1/metrics`** (unauthenticated by design;
firewall the endpoint to your private Prometheus subnet). Returns 503 when
metrics are disabled or `prometheus_client` is unavailable.

### Metrics

| Name                                       | Type      | Labels                       | Notes                                           |
|--------------------------------------------|-----------|------------------------------|-------------------------------------------------|
| `rt_ai_ids_http_requests_total`            | Counter   | `method`, `endpoint`, `status` | Endpoint = Flask route name (low-cardinality) |
| `rt_ai_ids_http_request_duration_seconds`  | Histogram | `method`, `endpoint`, `status` | Standard SRE buckets                          |
| `rt_ai_ids_predict_jobs_published_total`   | Counter   | `status` (`published`/`failed`) | Tracks API → broker enqueue                  |
| `rt_ai_ids_predict_jobs_completed_total`   | Counter   | `status` (`completed`/`failed`) | Tracks worker outcome                        |
| `rt_ai_ids_predict_job_duration_seconds`   | Histogram | `status`                       | Inference latency                            |
| `rt_ai_ids_alerts_persisted_total`         | Counter   | `risk_label`                   | DB writes by HIGH/MEDIUM/LOW                 |
| `rt_ai_ids_broker_dlq_total`               | Counter   | `stream`                       | Messages routed to a DLQ                     |
| `rt_ai_ids_pipeline_probe_status`          | Gauge     | (none)                         | 1=ok, 0.5=degraded, 0=down                   |
| `rt_ai_ids_pipeline_probe_latency_seconds` | Gauge     | (none)                         | Wall-clock of last probe                     |

### Sample Prometheus scrape config

```yaml
scrape_configs:
  - job_name: rt-ai-ids
    metrics_path: /api/v1/metrics
    static_configs:
      - targets: ["api.rt-ai-ids.internal:5000"]
```

### Configuration

| Env var            | Default | Purpose                        |
|--------------------|---------|--------------------------------|
| `METRICS_ENABLED`  | `true`  | Disable to return 503 globally |

---

## 3. OpenTelemetry tracing

Distributed tracing via the OTel SDK with OTLP/HTTP export. The API
auto-instruments Flask + SQLAlchemy + Redis. The inference worker
**continues** the trace by reading a W3C `traceparent` field that the API
embeds on every PredictJob payload, producing one span tree spanning
`HTTP request → broker enqueue → worker dequeue → model run → DB write`.

### Configuration

| Env var                       | Default                | Purpose                          |
|-------------------------------|------------------------|----------------------------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _(empty)_              | OTLP/HTTP collector URL          |
| `OTEL_SERVICE_NAME`           | `rt-ai-ids-api`        | Service name on every span       |

When the endpoint is empty the SDK still installs a tracer provider so
`trace_id` / `span_id` show up in logs — spans are simply dropped instead
of exported.

### Sample collector setup

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

exporters:
  otlphttp/tempo:
    endpoint: http://tempo:4318

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlphttp/tempo]
```

Then:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
```

---

## 4. Pipeline health probe

`GET /api/v1/health/pipeline` (JWT-protected) runs a synthetic predict job
through the **whole** publish → consume → persist → cache loop and reports
each stage's status. Suitable for an external uptime monitor (Pingdom /
Datadog Synthetic / Kubernetes startupProbe).

### Response

```json
{
  "status": "ok",
  "stages": [
    {"name": "publish",   "status": "ok", "latency_ms": 4.2},
    {"name": "inference", "status": "ok", "latency_ms": 41.7},
    {"name": "worker",    "status": "ok", "classification": "BENIGN"},
    {"name": "persist",   "status": "ok", "alert_id": 1234}
  ],
  "latency_ms": 47.3,
  "job_id": "probe-7f0a2b1c8d9e",
  "model_version": "v1.0.0",
  "model_dataset": "CICIDS2017"
}
```

`status` is `ok` (HTTP 200), `degraded` (HTTP 503), or `down` (HTTP 503).
Tune `PIPELINE_PROBE_TIMEOUT_SECONDS` (default `5`) for slower models.

### Why a synthetic probe?

`/health` (liveness) and `/ready` (DB connectivity) only confirm the API
process is alive — they will return 200 even if the inference worker has
silently stopped persisting alerts. The pipeline probe closes that gap by
asserting that an alert was actually written end-to-end.

---

## 5. Operating recipe

A typical production stack:

1. **Logs** → stdout → Docker → SIEM agent (Splunk UF / Elastic Agent /
   Vector / Fluent Bit) → SOC dashboard.
2. **Metrics** → Prometheus scrapes `/api/v1/metrics` every 15 s →
   Grafana dashboards + Alertmanager rules.
3. **Traces** → OTel collector → Tempo / Jaeger / Honeycomb → Grafana
   trace explorer (linked from log records by `trace_id`).
4. **Pipeline probe** → external synthetic monitor every 60 s → on-call
   pager when `status != "ok"` for 3 consecutive minutes.
