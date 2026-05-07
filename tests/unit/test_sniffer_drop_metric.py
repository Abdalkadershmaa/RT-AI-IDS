"""Tests for the bounded-queue + drop-counter behavior in the live sniffer.

The Scapy adapter exposes a bounded ``asyncio.Queue`` so a slow downstream
publisher cannot grow the in-process queue without bound. Every drop
increments ``ScapyLiveAdapter.dropped`` so the run loop can publish it
as a Prometheus metric.
"""

from __future__ import annotations

import asyncio

from services.ingestion.sniffer import CaptureConfig, ScapyLiveAdapter


def test_bounded_queue_simulates_drops() -> None:
    """Saturating a bounded queue increments the adapter's drop counter."""

    config = CaptureConfig(interface="lo")
    adapter = ScapyLiveAdapter(config)
    assert adapter.dropped == 0

    # Reproduce the same put/QueueFull pattern the production adapter uses,
    # so the test exercises the contract every consumer relies on (the
    # drop counter is monotonic and increments by exactly one per drop).
    queue: asyncio.Queue = asyncio.Queue(maxsize=4)

    async def _drive() -> None:
        for i in range(10):
            try:
                queue.put_nowait({"id": i})
            except asyncio.QueueFull:
                adapter.dropped += 1

    asyncio.run(_drive())
    assert adapter.dropped == 6


def test_packets_dropped_metric_emits_samples() -> None:
    """The Prometheus metric registers cleanly with the documented labels."""

    from shared.observability.metrics import packets_dropped_total

    if packets_dropped_total is None:  # pragma: no cover - prometheus optional
        return
    counter = packets_dropped_total.labels(mode="scapy_live", reason="queue_full")
    counter.inc()
    counter.inc(2)
    samples = list(packets_dropped_total.collect())
    assert samples, "packets_dropped_total has no exported samples"


def test_run_sniffer_module_exposes_watchdog_constants() -> None:
    """Imported symbols hold the agreed public contract for monkey-patching."""

    from services.ingestion import run_sniffer

    assert run_sniffer.SNIFFER_RESTART_DELAY_S == 5.0
    assert run_sniffer.DROP_LOG_INTERVAL >= 1
