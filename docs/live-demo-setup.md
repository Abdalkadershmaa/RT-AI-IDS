# Live Demo Setup — Wi-Fi Hotspot + Real Attacker

This guide walks you through running RT-AI-IDS against a **live, physical
Wi-Fi network** for your university graduation demo. The setup is:

```
┌──────────────────┐                ┌─────────────────────────────────┐
│ Attacker laptop  │ ── Wi-Fi ────▶ │ Your laptop (IDS host)          │
│ /  phone         │   (hotspot)    │   - Hotspot interface (wlan0/   │
└──────────────────┘                │     "Wi-Fi") = the gateway      │
                                    │   - RT-AI-IDS docker stack      │
                                    │   - ingestion sniffs the NIC    │
                                    │     in promiscuous mode         │
                                    └─────────────────────────────────┘
```

100% of the attacker's traffic physically transits your hotspot NIC, so
sniffing **that one interface** is enough.

> **Critical platform note.** Docker Desktop on Windows and macOS runs
> containers inside a Linux VM that **cannot see host Wi-Fi interfaces**,
> even with `--cap-add NET_RAW`. On those platforms the live-capture
> container will boot but observe **zero packets**. The fix is to run
> ingestion **natively on the host OS** (Section 4) while keeping the
> rest of the stack in Docker. Linux hosts are unaffected — `network_mode:
> host` works there.

---

## 1. Bring up the IDS stack (no capture yet)

```bash
git checkout devin/1777189317-phase3-microservices-refactor
make bootstrap                 # writes .env with random secrets
docker compose up --build -d   # api / db / redis / flow-builder / inference / migrations
docker compose ps
```

Expected: `api`, `db`, `redis` show **(healthy)**, `migrations` exits 0,
`flow-builder` and `inference` stay up. Don't start `ingestion` yet.

---

## 2. Find the right interface name

### 2a. Linux (Ubuntu / Fedora / Kali)

```bash
make list-interfaces
# or, equivalently:
ip -br link
```

Look for the wireless adapter you used to start the hotspot — usually
`wlan0`, `wlp3s0`, or similar. If you used `nmcli device wifi hotspot`,
the hotspot uses the same NIC; sniffing it is enough.

If you have a **USB Wi-Fi dongle** (recommended for monitor mode),
it'll typically be `wlan1`.

```bash
iw dev          # confirms which interface is in AP mode
iwconfig 2>/dev/null | grep -E '^[a-z]'
```

### 2b. Windows 10/11

Open **PowerShell as Administrator**:

```powershell
Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } |
    Select-Object Name, InterfaceDescription, MacAddress, LinkSpeed
```

Two adapters typically appear when the Mobile Hotspot is on:

| Name                              | InterfaceDescription                         |
| --------------------------------- | -------------------------------------------- |
| `Wi-Fi`                           | Intel Wireless-AC 9560 (your physical card)  |
| `Local Area Connection* 12`       | Microsoft Wi-Fi Direct Virtual Adapter #2    |

The **virtual adapter** (`Local Area Connection* 12`, exact number varies)
is the one carrying client traffic. Confirm with:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.PrefixOrigin -eq 'Manual' -or $_.PrefixOrigin -eq 'Dhcp' }
```

The interface that has the `192.168.137.1` (or similar) IP is your
hotspot's gateway interface. Use that exact name.

> If Scapy/Npcap shows the interface as a GUID (e.g.
> `\Device\NPF_{D2A1...}`), that's also valid — copy/paste it as-is.

### 2c. macOS

`ifconfig` then look for the AWDL/utun or the active Wi-Fi adapter
(usually `en0`). macOS native hotspot ("Internet Sharing") routes via
the same `en0`.

---

## 3. Configure `.env`

Edit `.env` (created by `make bootstrap`) and set:

```env
# Linux hotspot example
CAPTURE_INTERFACE=wlan0
CAPTURE_BPF_FILTER=tcp and not port 22
CAPTURE_PROMISCUOUS=true

# Windows hotspot example (note: spaces and '*' must be kept, no quotes)
# CAPTURE_INTERFACE=Local Area Connection* 12
```

**Why the BPF filter?** During a demo you want to exclude SSH / mDNS /
your own logging traffic so the alert feed stays signal-rich. Adjust to
taste. Leave it empty to capture everything.

**Why promiscuous?** Without promisc the kernel only delivers packets
addressed to your laptop's MAC. With promisc you also see traffic
between the attacker and any *other* hotspot client, which matters for
lateral-movement scenarios.

---

## 4. Start the ingestion service

### 4a. Linux — Docker (recommended, easiest)

```bash
docker compose --profile capture up -d ingestion
docker compose logs -f ingestion
```

You should immediately see:

```json
{"event":"ingestion_capture_starting","mode":"scapy_live",
 "interface":"wlan0","promiscuous":true,"bpf_filter":"tcp and not port 22"}
```

If you see `CAPTURE_INTERFACE='wlan0' not found on this host. Available
interfaces: lo, eth0, …` then ingestion is sniffing **inside the
container's namespace** instead of the host's. Make sure
`network_mode: host` is present in `docker-compose.yml` (it is by
default). On Linux this works; on Windows/macOS see 4b.

### 4b. Windows / macOS — run ingestion natively (Docker stack stays up)

Keep `docker compose up -d` running for `db`/`redis`/`api`/etc., but
**don't** start the ingestion container. Instead run the sniffer
directly on your host OS so it has access to the Wi-Fi card.

#### Windows 10/11 prerequisites

1. Install **[Npcap](https://npcap.com/)** (Wireshark's capture driver).
   Tick "WinPcap API-compatible mode" during install.
2. Install Python 3.11.
3. From the repo root in **PowerShell as Administrator**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements\ingestion.txt
   $env:CAPTURE_INTERFACE = "Local Area Connection* 12"
   $env:CAPTURE_PROMISCUOUS = "true"
   $env:REDIS_URL = "redis://127.0.0.1:6379/0"
   $env:ENVIRONMENT = "development"
   $env:SECRET_KEY = "dev"
   $env:JWT_SECRET_KEY = "dev"
   $env:ADMIN_PASSWORD = "dev"
   python -m services.ingestion.run_sniffer
   ```

#### macOS prerequisites

```bash
brew install libpcap
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements/ingestion.txt
set -a && source .env && set +a
sudo -E python -m services.ingestion.run_sniffer
```

#### Linux native (alternative to 4a)

```bash
make install
set -a && source .env && set +a
make ingest        # runs `sudo -E python -m services.ingestion.run_sniffer`
```

---

## 5. Verify packets are flowing

In a separate terminal:

```bash
# Stream the API logs — you should see flow events arriving
docker compose logs -f flow-builder inference
```

Or hit Redis directly:

```bash
docker compose exec redis redis-cli XLEN packet_ingest
docker compose exec redis redis-cli XLEN flow_inference
```

Both numbers should grow as the attacker's device sends traffic.

If `packet_ingest` is at zero after 30 s of attacker activity:
- Wrong interface name (Section 2).
- Promiscuous mode silently disabled — check the
  `ingestion_capture_starting` log line.
- Docker on Windows/macOS — see 4b.
- Hotspot client connected to a different NIC than you think (e.g. an
  Ethernet bridge instead of `wlan0`).

---

## 6. Launch attacks from the attacker device

> Only use these against your own demo network. **Never against
> third-party infrastructure.**

### 6a. Nmap stealth scan (triggers SYN-without-ACK alerts)

From the attacker laptop (`192.168.137.X`), with the IDS host at
`192.168.137.1`:

```bash
sudo nmap -sS -T4 -p 1-1024 192.168.137.1
sudo nmap -sV -A 192.168.137.1            # service+OS detection
```

Expected RT-AI-IDS reaction: many short flows from
`192.168.137.X → 192.168.137.1:*` with `SYN` set and zero or one
return packet. The flow builder closes them quickly and ships them to
inference; the resulting alerts appear in `GET /api/v1/alerts`.

### 6b. SYN flood / DoS (hping3)

```bash
sudo hping3 -S --flood -p 80 192.168.137.1            # SYN flood
sudo hping3 -1 --flood --rand-source 192.168.137.1    # ICMP flood w/ spoofed src
```

Expected reaction: a **large number of flows** with `SYN_only=true`
and `pkt_count=1`, plus a sharp jump in `flow_builder` throughput. Risk
labels skew toward `high` / `critical`. Drop logs (`ingestion_drops_observed`)
may appear if the attack rate exceeds 10k pkts/s — that's an honest
backpressure signal, not a bug.

### 6c. Slowloris (low-bandwidth HTTP DoS)

```bash
sudo apt install slowhttptest
slowhttptest -c 1000 -H -i 10 -r 200 -t GET -u http://192.168.137.1 -p 3
```

Expected reaction: long-lived TCP flows with low byte counts, `PSH`
flags, no `FIN`. These are the most "interesting" alerts because the
ML model has to discriminate them from legitimate slow connections.

### 6d. Real malware C2 sim (optional, advanced)

```bash
# Beacon every 60s with random small payload to a fake C2
while true; do
  curl --max-time 5 -s -o /dev/null \
    "http://192.168.137.1:8080/beacon?id=$(uuidgen)"
  sleep 60
done
```

Expected reaction: periodic short flows with a regular cadence — a
classic beaconing pattern.

---

## 7. Watch the alerts in real time

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$ADMIN_USERNAME\",\"password\":\"$ADMIN_PASSWORD\"}" \
  | jq -r .access_token)

watch -n 2 "curl -s -H 'Authorization: Bearer $TOKEN' \
  http://localhost:5000/api/v1/stats | jq ."
```

For the slide-deck demo, run this side-by-side with the attack
terminal so the audience sees `total_alerts` and the
`risk_distribution` histogram update live.

---

## 8. Demo-day checklist

Print this and tick it off 30 minutes before the presentation.

- [ ] Hotspot is on, attacker device successfully connected (`ping
      192.168.137.1` from attacker works).
- [ ] `CAPTURE_INTERFACE` in `.env` matches the hotspot NIC name (`make
      list-interfaces` confirms).
- [ ] `docker compose ps` shows api / db / redis healthy, flow-builder
      / inference up, migrations exited 0.
- [ ] Ingestion log shows `"ingestion_capture_starting"` with
      `"promiscuous": true`.
- [ ] Run a quick `nmap -sS -F 192.168.137.1` from the attacker —
      `XLEN packet_ingest` increases by hundreds.
- [ ] `curl /api/v1/stats` returns at least one alert.
- [ ] Browser tab open on `editor.swagger.io` with `docs/openapi.yaml`
      pasted — handy for the Q&A "show me the contract" question.
- [ ] Recording / screen mirroring tested, font size legible from back
      of room.
- [ ] **Backup PCAP** ready: `tcpdump -i wlan0 -w demo.pcap` recorded
      during a rehearsal. If the live demo gods are unkind, fall back
      to `CAPTURE_PCAP_FILE=demo.pcap`. Always. Have. A. PCAP.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `CAPTURE_INTERFACE='X' not found on this host. Available interfaces: …` | Typo or wrong namespace | Pick from the listed names. On Linux Docker, ensure `network_mode: host` is set. |
| Container starts but `XLEN packet_ingest` stays 0 | Docker on Win/macOS can't see host Wi-Fi | Run ingestion natively (Section 4b). |
| `Operation not permitted` on bind | `cap_add` missing or kernel hardening | Confirm `NET_RAW` and `NET_ADMIN` are in compose; on hardened distros, `setcap cap_net_raw,cap_net_admin=eip $(which python3.11)` for native runs. |
| Tons of packets but no alerts | Inference worker fell back to stub | Check `inference` logs for `model_load_failed`; either retrain or pin sklearn. |
| Promisc mode silently disabled by NIC driver | Some Realtek/Intel drivers refuse promisc on managed mode | Switch to a USB dongle in monitor mode and use `iw dev wlan1 set type monitor`. |
| Windows hotspot interface name has wildcard `*` | Real name, don't quote | `CAPTURE_INTERFACE=Local Area Connection* 12` (exactly, including the asterisk). |
| Encrypted traffic dominates the alert feed | TLS 1.3 hides L7 from sniffer | Use a permissive BPF filter; the model still classifies on L3/L4 features (which is the whole point). |

---

## 10. Cleanup after the demo

```bash
docker compose --profile capture down -v
# stop the hotspot too
nmcli connection down Hotspot
# revoke any temp credentials you generated
```

Re-source `.env` only inside isolated dev VMs — `make bootstrap`
writes plaintext secrets that are fine for development, **not** for
production.
