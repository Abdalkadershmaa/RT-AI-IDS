# RT-AI-IDS — Committee Demo Runbook

Single-page runbook for the live committee demo. **Read this once before
the demo, then keep it open as a checklist.** For deeper background on
interface selection, hotspot quirks, or extra attack scripts, see the
exhaustive [`live-demo-setup.md`](live-demo-setup.md).

> **Goal of the demo:** an attacker machine sends a real attack across
> the network. RT-AI-IDS captures the packets, classifies them, and the
> dashboard displays the alert in **under 5 seconds**.

---

## 0. Topology

Two machines on the same Wi-Fi (laptop hotspot recommended):

```
┌──────────────────┐                ┌─────────────────────────────────┐
│ MACHINE 2        │ ── attack ───▶ │ MACHINE 1 — IDS server          │
│  Attacker laptop │                │   Docker stack + browser        │
│  (Kali, Ubuntu)  │                │   on the hotspot's gateway IP   │
└──────────────────┘                └─────────────────────────────────┘
```

You will need **two terminals on Machine 1** (one for the stack, one for
ingestion logs) and **one terminal on Machine 2** (attacks).

---

## 1. Machine 1 — start the IDS stack

```bash
cd RT-AI-IDS
make bootstrap                      # writes a .env with random secrets (idempotent)
docker compose up -d                # api, db, redis, flow-builder, inference, migrations
docker compose ps                   # all services should be (healthy) or Up
```

> **One-time check.** If `docker compose ps` shows `inference` is missing
> or in `Restarting`, run `docker compose logs --tail=20 inference`. The
> usual cause on a fresh checkout is the model artifact mismatch covered
> in [`live-demo-setup.md`](live-demo-setup.md#troubleshooting). For the
> demo you can set `ALLOW_FALLBACK_CLASSIFIER=true` and
> `ENVIRONMENT=development` in `.env` and run `docker compose up -d` again
> — the deterministic fallback classifier still produces correct
> CRITICAL / HIGH alerts for nmap and hping3 traffic.

Verify the API is up:

```bash
curl -fsS http://localhost:5000/api/v1/health
# {"status":"ok"}

curl -fsS http://localhost:5000/api/v1/ready
# {"status":"ready"}
```

Read your admin password (printed by `make bootstrap`, also in `.env`):

```bash
grep ^ADMIN_PASSWORD .env
```

---

## 2. Machine 1 — start packet capture

The ingestion service is in the `capture` profile so it doesn't run by
default. Start it once you know which interface carries the attacker's
traffic:

```bash
make list-interfaces                # prints every interface name
```

Pick the hotspot interface (typically `wlan0` on Linux, the
`Local Area Connection* N` virtual adapter on Windows hotspot). Set it
in `.env`:

```bash
echo "CAPTURE_INTERFACE=wlan0" >> .env        # adjust name for your host
echo "CAPTURE_BPF_FILTER=tcp and not port 22" >> .env   # silence SSH chatter
echo "CAPTURE_PROMISCUOUS=true" >> .env
```

Then start ingestion:

```bash
docker compose --profile capture up -d ingestion
docker compose logs -f ingestion
```

Expected first log line:

```json
{"event":"ingestion_capture_starting","mode":"scapy_live",
 "interface":"wlan0","promiscuous":true,
 "bpf_filter":"tcp and not port 22","schema_version":"1.0"}
```

> **Windows / macOS hosts:** Docker Desktop containers can't see host
> Wi-Fi interfaces. Run ingestion natively instead — see
> [`live-demo-setup.md` §4b](live-demo-setup.md#4b-windows--macos--run-ingestion-natively-docker-stack-stays-up).

---

## 3. Machine 1 — open the dashboard

The API ships with a built-in single-page dashboard for live demos:

```
http://<machine-1-ip>:5000/api/v1/demo
```

In the on-screen form, log in with `admin` / `<ADMIN_PASSWORD from .env>`.
The page subscribes to the Server-Sent Events feed at
`/api/v1/alerts/stream` and renders new alerts as soon as they hit the
database (sub-second latency at the default 1 s SSE poll interval).

| Page area      | What it shows                                                |
| -------------- | ------------------------------------------------------------ |
| Top bar        | `● live` / `● disconnected (retrying)` connection indicator  |
| 4 stat cards   | Total alerts, Critical, High, Medium/Low counters            |
| Alert table    | id · time · risk · source IP · dest port · classification · score · rationale |

Project this browser tab on the committee screen.

> **No browser?** Same data is available via:
> ```bash
> TOKEN=$(curl -s -X POST http://localhost:5000/api/v1/auth/token \
>     -H "Content-Type: application/json" \
>     -d "{\"username\":\"admin\",\"password\":\"$ADMIN_PASSWORD\"}" | jq -r .access_token)
> curl -N -H "Authorization: Bearer $TOKEN" \
>      http://localhost:5000/api/v1/alerts/stream
> ```

---

## 4. Machine 2 — discover the IDS host's IP

On the IDS host (Machine 1):

```bash
ip -4 addr show wlan0 | awk '/inet /{print $2}' | cut -d/ -f1
# example: 10.42.0.1   ← this is what Machine 2 attacks
```

Confirm Machine 2 can reach it:

```bash
# from the attacker
ping -c 2 10.42.0.1
```

---

## 5. Machine 2 — run a real attack

> ⚠️ **Only run these against your own demo network.** Never against
> third-party infrastructure.

Replace `<IDS_IP>` with the address from Step 4.

### 5a. TCP SYN port scan (fast, visible result)

```bash
sudo nmap -sS -T4 -p 1-1024 <IDS_IP>
```

**Expected on the dashboard within 1–3 s:** a burst of `risk=high` /
`risk=critical` alerts with `classification` containing `port_scan` or
`syn_scan` and rationale entries like
`burst_of_syn_only_flows_to_distinct_ports`.

### 5b. SYN flood (DoS)

```bash
sudo hping3 -S --flood -p 80 <IDS_IP>
```

**Expected:** a steep climb in the **Critical** counter, repeated alerts
with `classification=DoS_SYN_flood`, `rationale=["high_pkt_rate_syn_only"]`.
Stop the attack after ~10 s (`Ctrl-C`).

### 5c. ICMP flood with spoofed sources (optional, dramatic)

```bash
sudo hping3 -1 --flood --rand-source <IDS_IP>
```

**Expected:** rationale includes `icmp_flood_spoofed_sources` and many
distinct `source_ip` values appear in the alert table.

### 5d. Slowloris (low-bandwidth HTTP DoS, optional)

```bash
sudo apt install -y slowhttptest
slowhttptest -c 1000 -H -i 10 -r 200 -t GET -u http://<IDS_IP>:5000 -p 3
```

**Expected:** longer-lived flows with `risk=high`, often classified as
`DoS_slowloris`.

---

## 6. Latency budget — what to point at on the screen

| Stage                                  | Typical | SLA budget |
| -------------------------------------- | -------:| ----------:|
| Packet → Scapy → Redis (`packet_ingest`) |   <50 ms | <500 ms |
| Flow builder → `flow_inference`        |  <200 ms | <1.0 s |
| Inference worker → DB write            |  <200 ms | <1.0 s |
| DB write → SSE frame → browser render  | <1.0 s  | <1.0 s |
| **Attack → dashboard alert (total)**   | **<2 s** | **<5 s** |

You can sanity-check the live latency at any time with the Prometheus
endpoint:

```bash
curl -s http://localhost:5000/api/v1/metrics | \
    grep -E 'rt_ai_ids_(http_request_duration|alerts_written|predict_jobs_in_flight)'
```

Or with the synthetic end-to-end probe (JWT-protected):

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/v1/auth/token \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"admin\",\"password\":\"$ADMIN_PASSWORD\"}" | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" \
     http://localhost:5000/api/v1/health/pipeline | jq .
# {"status":"ok","latency_ms":342,"stages":[{"name":"broker","status":"ok"},
#  {"name":"inference","status":"ok"},{"name":"db","status":"ok"}],
#  "model_version":"unknown","model_dataset":"CICIDS2017"}
```

---

## 7. Pre-demo checklist (15 minutes before)

- [ ] `.env` has `CAPTURE_INTERFACE` set to the hotspot adapter name.
- [ ] `docker compose ps` shows db / redis / api / flow-builder / inference healthy.
- [ ] `docker compose --profile capture ps` shows ingestion **Up**.
- [ ] `curl /api/v1/health` returns `200`.
- [ ] `curl /api/v1/health/pipeline` (with token) returns `status: ok`.
- [ ] Dashboard tab open at `http://localhost:5000/api/v1/demo`,
      logged in, top-right says `● live` (green).
- [ ] Attacker machine can `ping <IDS_IP>` successfully.
- [ ] Attacker terminal has `nmap` and `hping3` installed.
- [ ] (Optional) `slowhttptest` installed for the slowloris demo.
- [ ] One throwaway nmap scan was already executed and produced an
      alert — confirms the pipeline is hot before stage time.

---

## 8. After the demo — clean up

```bash
docker compose --profile capture down       # stop ingestion
docker compose down                         # stop the rest of the stack
# To wipe the database / redis state too:
docker compose down -v
```

If you used the deterministic fallback classifier, undo the `.env` toggle
before redeploying anywhere real:

```bash
sed -i 's/^ALLOW_FALLBACK_CLASSIFIER=true/ALLOW_FALLBACK_CLASSIFIER=false/' .env
```
