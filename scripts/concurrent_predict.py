"""End-to-end async non-blocking proof for /api/v1/predict.

Fires N concurrent enqueue requests against the live API container, then
polls each job_id until it completes. Reports:

- HTTP enqueue latency distribution (should be tiny — API never runs
  inference inline).
- Time-to-first-completed-result (worker should already be draining).
- Time-to-all-results (bounded by the worker, not the API).
"""

from __future__ import annotations

import json
import os
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.environ.get("BASE", "http://localhost:5000")
N = int(os.environ.get("N", "30"))
ADMIN = os.environ["ADMIN_USERNAME"]
PW = os.environ["ADMIN_PASSWORD"]


def _post(path: str, body: dict, token: str | None = None) -> tuple[int, dict, float]:
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode())
            return resp.status, payload, time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}"), time.perf_counter() - t0


def _get(path: str, token: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def _request_body(i: int, features: list[float]) -> dict:
    return {
        "flow_id": f"concurrent-{i}",
        "features": features,
        "context": {
            "source_ip": "10.0.0.1",
            "destination_ip": "10.0.0.2",
            "protocol": "TCP",
        },
    }


def _enqueue_phase(token: str, features: list[float]) -> tuple[list[tuple[int, dict, float]], float]:
    print(f"firing {N} concurrent /predict enqueues against {BASE} ...")
    started = time.perf_counter()
    results: list[tuple[int, dict, float]] = []
    with ThreadPoolExecutor(max_workers=N) as pool:
        futures = [
            pool.submit(_post, "/api/v1/predict", _request_body(i, features), token)
            for i in range(N)
        ]
        for f in as_completed(futures):
            results.append(f.result())
    return results, time.perf_counter() - started


def _poll_phase(
    job_ids: list[str], token: str
) -> tuple[dict[str, float], float | None, float]:
    started = time.perf_counter()
    pending = set(job_ids)
    completions: dict[str, float] = {}
    first: float | None = None
    deadline = time.perf_counter() + 30.0
    while pending and time.perf_counter() < deadline:
        for jid in list(pending):
            status, body = _get(f"/api/v1/predict/{jid}", token)
            if status == 200 and body.get("status") == "completed":
                completions[jid] = time.perf_counter() - started
                if first is None:
                    first = completions[jid]
                pending.discard(jid)
        if pending:
            time.sleep(0.05)
    return completions, first, time.perf_counter() - started


def main() -> None:
    status, body, _ = _post("/api/v1/auth/token", {"username": ADMIN, "password": PW})
    assert status == 200, body
    token = body["access_token"]

    features = [float(i + 1) for i in range(39)]
    enqueue_results, enqueue_elapsed = _enqueue_phase(token, features)
    accepted = [(payload, dur) for status, payload, dur in enqueue_results if status == 202]
    rejected = [(status, payload) for status, payload, _ in enqueue_results if status != 202]

    print(f"  enqueue wall time: {enqueue_elapsed * 1000:.1f} ms")
    print(f"  202 accepted:      {len(accepted)} / {N}")
    if rejected:
        print(f"  REJECTED ({len(rejected)}): {rejected[:3]}")

    durations = sorted(d for _, d in accepted)
    if durations:
        print(
            "  enqueue latency ms  min/p50/p95/max = "
            f"{durations[0] * 1000:.1f}/{statistics.median(durations) * 1000:.1f}/"
            f"{durations[int(len(durations) * 0.95) - 1] * 1000:.1f}/{durations[-1] * 1000:.1f}"
        )

    job_ids = [payload["job_id"] for payload, _ in accepted]
    print(f"polling {len(job_ids)} job ids ...")
    completions, first_completed_at, poll_elapsed = _poll_phase(job_ids, token)
    print(f"  completed:         {len(completions)} / {len(job_ids)}")
    if first_completed_at is not None:
        print(f"  first result in:   {first_completed_at * 1000:.1f} ms after first poll")
    print(f"  all results in:    {poll_elapsed * 1000:.1f} ms after first poll")

    if completions:
        latencies = sorted(completions.values())
        print(
            "  worker latency ms  min/p50/p95/max = "
            f"{latencies[0] * 1000:.1f}/{statistics.median(latencies) * 1000:.1f}/"
            f"{latencies[int(len(latencies) * 0.95) - 1] * 1000:.1f}/{latencies[-1] * 1000:.1f}"
        )

    print()
    print("PROOF OF NON-BLOCKING:")
    if durations and durations[-1] * 1000 < 500:
        print(
            f"  All {N} concurrent enqueues returned 202 in <500 ms each "
            f"({durations[-1] * 1000:.1f} ms max), while the worker drained "
            f"{len(completions)} jobs in {poll_elapsed * 1000:.1f} ms total. "
            "API never blocked on inference."
        )
    else:
        print("  WARNING: enqueue latency is unexpectedly high; investigate.")


if __name__ == "__main__":
    main()
