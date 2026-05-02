# Flutter Developer Guide — RT-AI-IDS Mobile Client

**Audience:** the Flutter engineer building the mobile companion for the RT-AI-IDS SOC dashboard.
**Scope:** everything you need to authenticate, list alerts in real time, submit a prediction, and plan for push notifications. No Flutter app code — just the data contract, connectivity matrix, polling pattern, Dart model classes, and a roadmap for FCM.
**Backend:** Flask 3 + Flask-JWT-Extended + Flask-Cors + Redis Streams + PostgreSQL. (It is *not* FastAPI — the JSON shapes still apply identically; just don't go looking for `uvicorn`.)

---

## 1. Mobile-readiness audit (the short version)

| Concern                       | Status                                                                                                     |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------- |
| JWT auth consistency          | ✅ All data endpoints behind `@jwt_required()`. Bearer header, single token format, 8-hour TTL.            |
| Lightweight bodies            | ✅ Alert row ≈ 13 small fields (~250 bytes JSON). `/stats` is one int + a tiny dict.                       |
| Pagination                    | ✅ Now supports `limit`, **`since_id`** (delta polling) and **`before_id`** (infinite scroll). Mobile-first. |
| ISO-8601 timestamps           | ✅ All `created_at` / `completed_at` are RFC-3339 UTC strings — `DateTime.parse` works directly.           |
| CORS for native clients       | ✅ N/A. Native Dart `http`/`dio` clients do not send `Origin`; CORS preflight is bypassed.                 |
| Stable error envelope         | ✅ Every non-2xx returns `{"error": "<code>", "status": <int>, "detail": ...}`.                            |
| Push notifications            | ❌ Not yet. Outline below — we'll wire FCM in a follow-up PR.                                              |
| Rate limiting                 | ⚠️ None enforced today; please be polite (3-second polling cadence is fine).                               |

**Conclusion:** the API is mobile-ready as of this PR. Two new query parameters were added so a phone on flaky LTE doesn't have to re-download the entire alerts feed every poll.

---

## 2. Connectivity matrix — how the phone reaches your laptop

The Flask API binds to port `5000`. Where the phone resolves "the API" depends on the host:

| Where Flutter runs                  | Base URL                                            | Notes                                                                                                  |
| ----------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Android Emulator                    | `http://10.0.2.2:5000`                              | `10.0.2.2` is the emulator's alias for the host machine's `localhost`. **Not `127.0.0.1`** — that loops back to the emulator itself. |
| iOS Simulator                       | `http://localhost:5000`                             | Simulator shares the host's network namespace.                                                         |
| Physical phone, same Wi-Fi          | `http://<laptop-LAN-IP>:5000`                       | Find via `ipconfig` (Windows) / `ip -br addr` (Linux) / `ifconfig` (macOS). Make sure your firewall allows inbound 5000. |
| Physical phone on demo Wi-Fi hotspot | `http://192.168.137.1:5000` (Windows mobile hotspot default) | The laptop is the gateway, so the gateway IP is the API host.                                          |
| Production                          | `https://<your-domain>/api/v1/...` behind a reverse proxy | Always TLS in production. Pin the certificate if you can.                                              |

⚠️ **Android cleartext traffic.** Android 9+ blocks `http://` by default. For local dev, add a `network_security_config.xml` allowing cleartext to `10.0.2.2` and your laptop LAN IP, and reference it from `AndroidManifest.xml`. Production must be TLS.

---

## 3. Authentication flow

Single endpoint, simple Bearer token, no refresh endpoint (re-login on 401).

### Step 1 — exchange credentials for a JWT

`POST /api/v1/auth/token`

```json
// Request
{ "username": "admin", "password": "<from .env ADMIN_PASSWORD>" }
```

```json
// 200 OK
{ "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

```json
// 401
{ "error": "invalid_credentials", "status": 401 }
```

### Step 2 — attach the token to every other request

```
GET /api/v1/alerts?limit=20 HTTP/1.1
Host: 10.0.2.2:5000
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
Accept: application/json
```

### Step 3 — handle expiry

The token TTL is **8 hours**. When it expires, every protected endpoint returns:

```json
// 401
{ "error": "expired_token", "status": 401 }
```

Recommended Flutter behaviour: a single `AuthInterceptor` that on `401 expired_token` (or `401 invalid_token`) re-calls `/auth/token` once with cached credentials and retries the original request. If the re-login also fails, navigate to the Login screen.

### Step 4 — store the JWT safely

Use **`flutter_secure_storage`** (Keychain on iOS, EncryptedSharedPreferences on Android). **Do not** use `SharedPreferences` directly — JWTs in plaintext SharedPreferences are a known mobile-malware target.

---

## 4. Endpoints map

`{base}` = the value from §2's connectivity matrix.

### 4.1 Health

| Method | Path                       | Auth | Notes                                                               |
| ------ | -------------------------- | ---- | ------------------------------------------------------------------- |
| GET    | `{base}/api/v1/health`     | —    | `{ "status": "ok" }`. Liveness probe — always 200 if the process is up. |
| GET    | `{base}/api/v1/ready`      | —    | `{ "status": "ready" }` (200) or `{ "status": "not_ready" }` (503).   |

### 4.2 Auth

| Method | Path                        | Auth | Notes                                                  |
| ------ | --------------------------- | ---- | ------------------------------------------------------ |
| POST   | `{base}/api/v1/auth/token`  | —    | See §3.                                                |

### 4.3 Predict (async)

`POST /api/v1/predict` — enqueue a prediction job. Returns **immediately** with `202` and a `job_id`. Poll the result.

```json
// Request
{
  "flow_id": "optional-client-correlator",
  "features": [/* exactly 39 finite floats */],
  "context": {
    "protocol": "TCP",
    "source_ip": "192.168.137.42",
    "destination_ip": "192.168.137.1"
  }
}
```

```json
// 202 Accepted
{
  "job_id": "8f2b1c4a6d9e4f80b2d9e7c3a1f0e5d4",
  "status": "pending",
  "poll_url": "/api/v1/predict/8f2b1c4a6d9e4f80b2d9e7c3a1f0e5d4"
}
```

`GET /api/v1/predict/{job_id}` — poll the cached result.

```json
// 202 — pending
{ "job_id": "...", "status": "pending", /* all other fields null/empty */ }

// 200 — completed
{
  "job_id": "...",
  "status": "completed",
  "flow_id": "...",
  "classification": "DoS Hulk",
  "probability": 0.982,
  "risk_label": "very_high",
  "risk_score": 0.982,
  "rationale": ["ml_model_flagged_flow"],
  "alert_id": 142,
  "error": null,
  "completed_at": "2026-04-26T12:14:25.712Z"
}

// 200 — failed
{ "job_id": "...", "status": "failed", "error": "model_artifact_incompatible", /* ... */ }

// 404 — unknown or expired (TTL = PREDICT_RESULT_TTL_SECONDS, default 3600s)
{ "error": "not_found", "status": 404, "detail": "job_id unknown or expired" }
```

**Polling cadence for predict:** start at **300 ms**, double on each pending response, cap at **3 s**, give up at **30 s** wall-clock and surface "timed out — check the Alerts page".

### 4.4 Alerts (with mobile-friendly cursor pagination)

| Query param | Type    | Default | Behaviour                                                                                                          |
| ----------- | ------- | ------- | ------------------------------------------------------------------------------------------------------------------ |
| `limit`     | int     | 50      | `1 ≤ limit ≤ 500`.                                                                                                 |
| `since_id`  | int     | —       | Returns rows with `id > since_id`, **ascending**. Use this for delta polling on the live feed.                     |
| `before_id` | int     | —       | Returns rows with `id < before_id`, **newest-first**. Use this for infinite-scroll into older history.             |

`since_id` and `before_id` are mutually exclusive — sending both returns 400.

```bash
# First load — newest 50 (legacy default)
GET /api/v1/alerts?limit=50

# Live polling — only what's new since we last saw id=142
GET /api/v1/alerts?since_id=142&limit=50

# Pull-to-refresh older — load 50 rows older than the bottom-most card we have
GET /api/v1/alerts?before_id=93&limit=50
```

```json
// 200 — list of Alert objects
[
  {
    "id": 142,
    "flow_id": "8f2b1c4a6d9e4f80b2d9e7c3a1f0e5d4",
    "source_ip": "192.168.137.42",
    "source_port": 53412,
    "destination_ip": "192.168.137.1",
    "destination_port": 80,
    "protocol": "TCP",
    "classification": "DoS Hulk",
    "probability": 0.982,
    "risk_label": "very_high",
    "risk_score": 0.982,
    "rationale": ["ml_model_flagged_flow"],
    "created_at": "2026-04-26T12:14:25.712Z"
  }
]
```

`GET /api/v1/alerts/{id}` — single alert (same shape as the array entry). 404 envelope if not found.

### 4.5 Stats

`GET /api/v1/stats`

```json
{
  "total_alerts": 142,
  "risk_distribution": {
    "minimal": 18, "low": 32, "medium": 47, "high": 29, "very_high": 16
  }
}
```

`risk_distribution` keys are present **only** if their count > 0. Default missing keys to `0` in the UI.

### 4.6 Error envelope (all non-2xx)

```json
{ "error": "<snake_case code>", "status": 400, "detail": "<optional>" }
```

Common error codes the Flutter app should map to user-facing strings: `invalid_request`, `invalid_credentials`, `expired_token`, `invalid_token`, `unauthorized`, `not_found`, `internal_server_error`.

---

## 5. Real-time strategy — polling, not WebSockets (yet)

### Why polling

We evaluated SSE and WebSockets; they're deferred until the post-demo backlog. Reasons:

1. The inference worker writes alerts directly to Postgres; there is no server-push fanout today (would need a Redis Pub/Sub bus to add).
2. Flask + gunicorn behind a reverse proxy buffers responses by default — SSE needs `X-Accel-Buffering: no` everywhere or the stream stalls. Mobile networks add another buffering layer (carrier proxies).
3. Demo-grade load is O(1–10 alerts/second). A `SELECT … WHERE id > $1 ORDER BY id ASC LIMIT 50` against an indexed `id` column is sub-millisecond on Postgres. 3-second polling = ~0.3 rps per device.
4. **Mobile network reality:** persistent WebSocket connections drain battery and are aggressively killed by iOS/Android when the app backgrounds. A polling loop is paused on app suspension by the OS for free; resuming reconnects automatically.

### Recommended cadences for Flutter

| View / state                          | Endpoint                                            | Cadence                | Notes                                                        |
| ------------------------------------- | --------------------------------------------------- | ---------------------- | ------------------------------------------------------------ |
| Foreground — live alerts list         | `GET /api/v1/alerts?since_id={maxSeenId}&limit=50`  | every **3 s**          | Keep `maxSeenId` in `Provider`/`Riverpod`. Append ascending; trim list to 200 client-side. |
| Foreground — KPI bar (`total_alerts`) | `GET /api/v1/stats`                                 | every **5 s**          | Cheap query.                                                 |
| Foreground — predict result           | `GET /api/v1/predict/{job_id}`                      | exp. backoff 300 ms→3 s | Cap total wait at 30 s.                                      |
| Foreground — alert detail screen      | `GET /api/v1/alerts/{id}`                           | once on open           | Rows are immutable after insert.                             |
| Background (app suspended)            | **don't poll**                                      | —                      | iOS/Android will throttle/kill you. Use FCM (§7) for true background reliability. |
| Reconnecting (network came back)      | `GET /api/v1/alerts?since_id={maxSeenId}&limit=500` | once                   | Catch up on the gap. Then resume the 3 s loop.               |

### The dedupe pattern, in pseudo-Dart

```dart
// State (Riverpod / Provider / Bloc — your choice).
int _maxSeenId = -1;
final List<Alert> _feed = [];

Future<void> _pollOnce() async {
  final cursor = _maxSeenId < 0 ? '' : '?since_id=$_maxSeenId&limit=50';
  // For the very first load, use ?limit=50 with no cursor to get newest-first.
  final url = _maxSeenId < 0
      ? '$baseUrl/api/v1/alerts?limit=50'
      : '$baseUrl/api/v1/alerts$cursor';

  final response = await _authedGet(url);
  if (response.statusCode != 200) return;

  final List rows = jsonDecode(response.body) as List;
  if (rows.isEmpty) return;

  // since_id returns ascending; first load returns newest-first.
  final newAlerts = rows.map((r) => Alert.fromJson(r)).toList();
  for (final a in newAlerts) {
    if (a.id > _maxSeenId) _maxSeenId = a.id;
  }
  _feed.insertAll(0, newAlerts.reversed); // newest at top
  if (_feed.length > 200) _feed.removeRange(200, _feed.length);
}
```

(Pseudo-code only — the user asked for no Flutter code in the design phase. Use this purely as a reference for the dataflow.)

### Pull-to-refresh / infinite-scroll

* Pull-to-refresh: just call `_pollOnce()` immediately (don't wait for the timer).
* Infinite-scroll older: when the list bottom is reached, request `?before_id={feed.last.id}&limit=50` and append the rows in the order returned (newest-first → already correct for a downward-scrolling feed).

---

## 6. Dart data models

Drop these classes into `lib/models/`. They're complete `fromJson` / `toJson` implementations that match the backend Pydantic schemas exactly.

### 6.1 Risk label enum

```dart
enum RiskLabel { minimal, low, medium, high, veryHigh, unknown }

RiskLabel riskLabelFromString(String? s) {
  switch (s) {
    case 'minimal':   return RiskLabel.minimal;
    case 'low':       return RiskLabel.low;
    case 'medium':    return RiskLabel.medium;
    case 'high':      return RiskLabel.high;
    case 'very_high': return RiskLabel.veryHigh;
    default:          return RiskLabel.unknown;
  }
}

String riskLabelToString(RiskLabel r) {
  switch (r) {
    case RiskLabel.minimal:   return 'minimal';
    case RiskLabel.low:       return 'low';
    case RiskLabel.medium:    return 'medium';
    case RiskLabel.high:      return 'high';
    case RiskLabel.veryHigh:  return 'very_high';
    case RiskLabel.unknown:   return 'unknown';
  }
}
```

### 6.2 Alert

```dart
class Alert {
  final int id;
  final String flowId;
  final String sourceIp;
  final int sourcePort;
  final String destinationIp;
  final int destinationPort;
  final String protocol;          // typically "TCP" / "UDP" / "ICMP" / ""
  final String classification;    // free-form (e.g. "DoS Hulk", "PortScan", "Benign")
  final double probability;       // 0..1
  final RiskLabel riskLabel;
  final double riskScore;         // 0..1
  final List<String> rationale;
  final DateTime createdAt;       // UTC

  const Alert({
    required this.id,
    required this.flowId,
    required this.sourceIp,
    required this.sourcePort,
    required this.destinationIp,
    required this.destinationPort,
    required this.protocol,
    required this.classification,
    required this.probability,
    required this.riskLabel,
    required this.riskScore,
    required this.rationale,
    required this.createdAt,
  });

  factory Alert.fromJson(Map<String, dynamic> json) => Alert(
    id:               json['id'] as int,
    flowId:           json['flow_id'] as String,
    sourceIp:         json['source_ip'] as String,
    sourcePort:       json['source_port'] as int,
    destinationIp:    json['destination_ip'] as String,
    destinationPort: (json['destination_port'] as num).toInt(),
    protocol:         json['protocol'] as String? ?? '',
    classification:   json['classification'] as String,
    probability:     (json['probability'] as num).toDouble(),
    riskLabel:        riskLabelFromString(json['risk_label'] as String?),
    riskScore:       (json['risk_score'] as num).toDouble(),
    rationale:        List<String>.from(json['rationale'] as List? ?? const []),
    createdAt:        DateTime.parse(json['created_at'] as String).toUtc(),
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'flow_id': flowId,
    'source_ip': sourceIp,
    'source_port': sourcePort,
    'destination_ip': destinationIp,
    'destination_port': destinationPort,
    'protocol': protocol,
    'classification': classification,
    'probability': probability,
    'risk_label': riskLabelToString(riskLabel),
    'risk_score': riskScore,
    'rationale': rationale,
    'created_at': createdAt.toUtc().toIso8601String(),
  };
}
```

### 6.3 Stats

```dart
class Stats {
  final int totalAlerts;
  final Map<RiskLabel, int> riskDistribution;

  const Stats({required this.totalAlerts, required this.riskDistribution});

  factory Stats.fromJson(Map<String, dynamic> json) {
    final raw = (json['risk_distribution'] as Map?) ?? const {};
    final distribution = <RiskLabel, int>{
      for (final r in RiskLabel.values) r: 0,
    };
    raw.forEach((key, value) {
      distribution[riskLabelFromString(key as String?)] = (value as num).toInt();
    });
    return Stats(
      totalAlerts: (json['total_alerts'] as num).toInt(),
      riskDistribution: distribution,
    );
  }
}
```

### 6.4 Predict request / response

```dart
class PredictRequest {
  final String? flowId;
  final List<double> features;            // exactly 39 finite floats
  final Map<String, dynamic> context;

  const PredictRequest({
    this.flowId,
    required this.features,
    this.context = const {},
  }) : assert(features.length == 39, 'features must contain exactly 39 floats');

  Map<String, dynamic> toJson() => {
    if (flowId != null) 'flow_id': flowId,
    'features': features,
    'context': context,
  };
}

enum PredictStatus { pending, completed, failed, unknown }

PredictStatus _predictStatus(String? s) {
  switch (s) {
    case 'pending':   return PredictStatus.pending;
    case 'completed': return PredictStatus.completed;
    case 'failed':    return PredictStatus.failed;
    default:          return PredictStatus.unknown;
  }
}

class PredictAccepted {
  final String jobId;
  final String pollUrl;

  const PredictAccepted({required this.jobId, required this.pollUrl});

  factory PredictAccepted.fromJson(Map<String, dynamic> json) => PredictAccepted(
    jobId: json['job_id'] as String,
    pollUrl: json['poll_url'] as String,
  );
}

class PredictResult {
  final String jobId;
  final PredictStatus status;
  final String? flowId;
  final String? classification;
  final double? probability;
  final RiskLabel? riskLabel;
  final double? riskScore;
  final List<String> rationale;
  final int? alertId;
  final String? error;
  final DateTime? completedAt;

  const PredictResult({
    required this.jobId,
    required this.status,
    this.flowId,
    this.classification,
    this.probability,
    this.riskLabel,
    this.riskScore,
    this.rationale = const [],
    this.alertId,
    this.error,
    this.completedAt,
  });

  factory PredictResult.fromJson(Map<String, dynamic> json) => PredictResult(
    jobId: json['job_id'] as String,
    status: _predictStatus(json['status'] as String?),
    flowId: json['flow_id'] as String?,
    classification: json['classification'] as String?,
    probability: (json['probability'] as num?)?.toDouble(),
    riskLabel: json['risk_label'] != null
        ? riskLabelFromString(json['risk_label'] as String)
        : null,
    riskScore: (json['risk_score'] as num?)?.toDouble(),
    rationale: List<String>.from(json['rationale'] as List? ?? const []),
    alertId: json['alert_id'] as int?,
    error: json['error'] as String?,
    completedAt: json['completed_at'] != null
        ? DateTime.parse(json['completed_at'] as String).toUtc()
        : null,
  );
}
```

### 6.5 Suggested package set (no code, just dependencies)

| Need                          | Package                                 |
| ----------------------------- | --------------------------------------- |
| HTTP client                   | `dio` (preferred) or `http`             |
| Secure JWT storage            | `flutter_secure_storage`                |
| State management              | `flutter_riverpod` (or your team's pick) |
| Push notifications            | `firebase_core` + `firebase_messaging`  |
| App-lifecycle awareness       | `WidgetsBindingObserver` (built-in)     |
| Connectivity changes          | `connectivity_plus`                     |

---

## 7. Push notifications — proposed plan (NOT shipped in this PR)

The current polling design is good for foreground UX but **iOS/Android will not let your app keep polling once it backgrounds**. For "ping me when an attack happens, even if my app is closed", we need server-pushed notifications via **Firebase Cloud Messaging (FCM)**.

### High-level architecture

```
inference worker  ──Postgres write──►  alerts table
        │
        └──PUBLISH alerts.new {alert_json}──►  Redis Pub/Sub
                                                     │
                                                     ▼
                                            services/notifications  (new)
                                                     │
                                                     ▼
                                                  FCM API
                                                     │
                                                     ▼
                                       APNs / FCM       Android device
                                       (Apple)           (Google)
                                                     │
                                                     ▼
                                          Flutter app shows banner
```

### Backend changes required (small, additive)

1. **Inference worker** — after `session.commit()`, also `redis.publish("alerts.new", json.dumps(alert_dict))`. ~5 lines.
2. **New service** `services/notifications/` — subscribes to `alerts.new`, fetches device tokens from a new `device_tokens` table, calls `firebase-admin`'s `messaging.send_multicast` with a payload like:
   ```json
   {
     "notification": {
       "title": "RT-AI-IDS — DoS Hulk detected",
       "body": "From 192.168.137.42 → :80 (very_high)"
     },
     "data": { "alert_id": "142", "risk_label": "very_high" }
   }
   ```
3. **New endpoints** on the API:
   - `POST /api/v1/devices` — body `{ "fcm_token": "...", "platform": "android"|"ios" }`, JWT-protected. Inserts/updates the row.
   - `DELETE /api/v1/devices/{token}` — JWT-protected. Used on logout.
4. **New env vars** — `FCM_SERVICE_ACCOUNT_JSON_PATH` (mounted via Docker secret), `NOTIFICATIONS_ENABLED=true|false`.
5. **New Alembic migration** — `device_tokens` table:
   ```
   id BIGSERIAL PK
   user_id INT (FK to admin user — nullable until per-user auth lands)
   fcm_token TEXT UNIQUE NOT NULL
   platform VARCHAR(16) NOT NULL
   created_at TIMESTAMPTZ NOT NULL
   last_seen_at TIMESTAMPTZ NOT NULL
   ```

### Flutter side (steps, not code)

1. `firebase_core` + `firebase_messaging` packages, add `google-services.json` (Android) and `GoogleService-Info.plist` (iOS) to the app.
2. On app start, request `messaging.requestPermission()` (iOS) and grab `messaging.getToken()`.
3. `POST /api/v1/devices` with the FCM token after every login (token can rotate).
4. `DELETE /api/v1/devices/{token}` on logout.
5. Listen with `FirebaseMessaging.onMessage` (foreground), `FirebaseMessaging.onMessageOpenedApp` (tap), and `FirebaseMessaging.onBackgroundMessage` (registered top-level handler).
6. On notification tap, deep-link to the alert detail screen using `data.alert_id`.

### Effort estimate

- Backend: ~1 day (incl. migration, tests, FCM service-account wiring).
- Flutter: ~0.5 day (incl. permission UX, deep-link handler).
- Demo: should we want it for the graduation demo, this is a focused 1.5-day chunk of work. **Say the word and I'll open a PR.**

### Cost & operational notes

- FCM is free for the volumes we expect (~thousands of messages/day per device).
- iOS requires an Apple Developer account ($99/year) and an APNs Auth Key uploaded to Firebase. Plan for this *before* demo day.
- Token rotation is automatic; the backend should treat `messaging/registration-token-not-registered` errors as "delete this device row".

---

## 8. Demo-day checklist for the Flutter dev

1. Start the backend: `docker compose up -d` on the laptop.
2. Find the laptop's hotspot IP and put it in the Flutter app's environment file.
3. On a physical phone connected to the laptop hotspot, launch the app — login with `admin` / `<your ADMIN_PASSWORD>`.
4. Connect a second device to the hotspot and run `nmap -sS -T4 <victim_ip>` (see `docs/live-demo-setup.md` for the full attacker playbook).
5. Watch the alerts feed populate within 3 seconds.
6. Tap an alert to verify the detail screen.
7. Verify the KPI counters tick up.

If notifications are wired (per §7), the phone will buzz **even when the app is in the background**.

---

## 9. Related documents

- **Frontend Integration & API Contract Guide (React companion)** — same data, web context: handed to your UI designer separately.
- **OpenAPI 3.1 spec** — [`docs/openapi.yaml`](./openapi.yaml). Paste into [editor.swagger.io](https://editor.swagger.io/) for an interactive schema explorer; or generate Dart client models with `openapi-generator` if you prefer.
- **Live demo setup** — [`docs/live-demo-setup.md`](./live-demo-setup.md). Network-layer setup for the graduation demo.
- **Threat model** — [`docs/threat-model.md`](./threat-model.md). Worth a 5-minute read before shipping the mobile client.

---

## 10. Open questions you can hand back to the backend team

If any of these are blockers, tell me and I'll prioritise:

1. Do you want **multi-user auth** (per-user JWT, per-user device-token table) before FCM ships? Today there is one bootstrap admin only.
2. Should `/alerts` support a **`risk_label` filter** (e.g. `?risk_label=high,very_high`) so the mobile high-priority view doesn't have to download all classes?
3. Should **tap-to-acknowledge** an alert be a thing? (Would need a new column + `PATCH /api/v1/alerts/{id}` endpoint.)
4. TLS / domain — what's the planned production hostname? Required for iOS App Store review (no plain HTTP).

Ship questions back as a comment on the PR or in chat — happy to scope and implement any of them.
