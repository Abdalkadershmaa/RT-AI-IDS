"""Regression tests for ScapyLiveAdapter's asyncio thread-safety.

Scapy's AsyncSniffer invokes the ``prn`` callback on a kernel thread. A naive
implementation called ``asyncio.Queue.put_nowait()`` from that thread, which
is NOT thread-safe (cpython issue #97970): the awaiting coroutine may not be
woken reliably and packets can stall forever in the queue.

The fix uses ``loop.call_soon_threadsafe()`` so the put runs on the event
loop. We replay that exact pattern here without depending on Scapy.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from services.ingestion.sniffer import CaptureConfig, ScapyLiveAdapter
from shared.schemas import PacketEvent


def _fake_packet_event(src_ip: str = "10.0.0.1", dst_ip: str = "10.0.0.2") -> PacketEvent:
    return PacketEvent(
        timestamp=1.0,
        src_ip=src_ip,
        src_port=1234,
        dst_ip=dst_ip,
        dst_port=80,
        protocol="TCP",
        payload_size=64,
        tcp_flags={
            "SYN": True,
            "ACK": False,
            "FIN": False,
            "RST": False,
            "PSH": False,
            "URG": False,
        },
        metadata={},
    )


class _FakeSniffer:
    """Drop-in for ``scapy.AsyncSniffer`` that fires N packets from a thread."""

    def __init__(self, prn, packet_count: int = 50, **_kwargs) -> None:
        self.prn = prn
        self.packet_count = packet_count
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        for i in range(self.packet_count):
            # Sentinel that the patched _convert_packet recognizes.
            self.prn(("fake-pkt", i))

    def stop(self) -> None:
        if self._thread is not None:
            self._thread.join(timeout=2)


def test_packets_are_delivered_from_a_kernel_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: callback runs on a non-loop thread, queue still wakes the awaiter."""

    def _fake_convert(pkt) -> PacketEvent | None:
        if isinstance(pkt, tuple) and pkt[0] == "fake-pkt":
            return _fake_packet_event(src_ip=f"10.0.0.{pkt[1] % 250}")
        return None

    monkeypatch.setattr("services.ingestion.sniffer._convert_packet", _fake_convert)
    monkeypatch.setattr("services.ingestion.sniffer.AsyncSniffer", _FakeSniffer)

    adapter = ScapyLiveAdapter(CaptureConfig(interface="lo"))

    async def _drain() -> list[PacketEvent]:
        delivered: list[PacketEvent] = []
        async for event in adapter.packets():
            delivered.append(event)
            if len(delivered) >= 50:
                break
        return delivered

    delivered = asyncio.run(asyncio.wait_for(_drain(), timeout=5.0))

    assert len(delivered) == 50
    assert all(isinstance(e, PacketEvent) for e in delivered)


def test_overflow_increments_drop_counter_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the bounded queue overflows, drops are counted instead of raising."""

    def _fake_convert(pkt) -> PacketEvent | None:
        if isinstance(pkt, tuple) and pkt[0] == "fake-pkt":
            return _fake_packet_event()
        return None

    monkeypatch.setattr("services.ingestion.sniffer._convert_packet", _fake_convert)

    class _BurstySniffer(_FakeSniffer):
        def __init__(self, prn, **kwargs) -> None:
            super().__init__(prn, packet_count=10_050, **kwargs)

    monkeypatch.setattr("services.ingestion.sniffer.AsyncSniffer", _BurstySniffer)

    adapter = ScapyLiveAdapter(CaptureConfig(interface="lo"))

    async def _run() -> None:
        iterator = adapter.packets().__aiter__()
        # Pull a few packets, then let the kernel thread enqueue the rest and
        # the loop process the call_soon_threadsafe callbacks. After all
        # callbacks run, the queue tail must be dropped.
        for _ in range(5):
            await asyncio.wait_for(iterator.__anext__(), timeout=2.0)
        for _ in range(20):
            await asyncio.sleep(0.05)
            if adapter.dropped > 0:
                break

    asyncio.run(asyncio.wait_for(_run(), timeout=10.0))

    # 10,050 events queued for a 10,000-slot buffer with only 5 consumed must
    # produce drops accounted for in the counter.
    assert adapter.dropped > 0
