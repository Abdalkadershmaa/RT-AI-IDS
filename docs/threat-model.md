# Threat Model

Scope: the RT-AI-IDS deployment itself (API, workers, broker, DB), **not** the
networks it is observing.

## Trust boundaries

```
+----------------+   public network   +---------+   container net   +----------+
|  HTTP client   | -----------------> |   api   | ----------------> |  redis   |
+----------------+                    +---------+                   +----------+
                                          |                              |
                                          v                              v
                                       +-----+                      +----------+
                                       | db  |                      | workers  |
                                       +-----+                      +----------+
```

| Boundary               | Auth mechanism                                        |
| ---------------------- | ------------------------------------------------------ |
| Client → API           | JWT (HS256, 8h expiry, 32-byte+ secret enforced)       |
| API → Redis            | TLS not yet enforced; assume isolated container net    |
| API → PostgreSQL       | Username/password; rotate via `.env`                   |
| Workers → Redis / DB   | Same secrets as API; same trust boundary               |

## Risks & mitigations

| Risk                                     | Mitigation                                                                                                  |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Default secrets in production            | Settings layer raises `InsecureDefaultSecretError` at startup unless `ENVIRONMENT=development\|test`.       |
| Brute-force admin login                  | **Open** — rate limiting not yet implemented. Tracked as audit finding S4. Use a strong `ADMIN_PASSWORD`.   |
| Pickle / dill deserialization (RCE)      | Models are mounted read-only and now SHA-256 verified via `models/manifest.sha256.json` before any deserialization. |
| Oversized request bodies                 | `MAX_CONTENT_LENGTH = 1 MiB` on the Flask app.                                                              |
| Denial-of-service via unbounded queue    | Bounded `asyncio.Queue` in capture path with a drop counter; flow_builder has `max_flows` cap.              |
| NaN / inf model inputs                   | pydantic validator on `features` rejects non-finite floats.                                                 |
| JWT replay                               | 8 h expiry. Revocation list **not** implemented; planned for the user-account milestone.                    |
| Long-running inference blocking the API  | Async predict path: API enqueues on `predict_jobs`, returns 202, never runs the model in-request.           |
| Secret leakage in logs                   | JSON logger never logs request bodies or settings; correlation IDs are non-sensitive UUIDs.                 |

## Out of scope

- Network-level threats against the IDS host (firewalled at the deployment
  level).
- Threats against the underlying ML model (poisoning, evasion). Tracked as
  separate research work.
- Frontend security — the legacy templates have been removed; the planned
  React SOC dashboard will land in a separate repo with its own threat model.
