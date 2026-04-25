from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from typing import AsyncIterator

from scapy.all import AsyncSniffer, IP, TCP, UDP, PcapReader  # type: ignore

from shared.schemas import PacketEvent


@dataclass
class CaptureConfig:
    interface: str | None = None
    bpf_filter: str | None = None
    pcap_file: str | None = None
    tcpdump_cmd: str | None = None


class PacketCaptureAdapter:
    async def packets(self) -> AsyncIterator[PacketEvent]:
        raise NotImplementedError


class ScapyLiveAdapter(PacketCaptureAdapter):
    def __init__(self, config: CaptureConfig) -> None:
        self.config = config

    async def packets(self) -> AsyncIterator[PacketEvent]:
        # Bound queue to prevent unbounded memory growth under packet bursts.
        queue: asyncio.Queue[PacketEvent] = asyncio.Queue(maxsize=10_000)

        def on_packet(pkt) -> None:
            event = _convert_packet(pkt)
            if event:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Drop newest burst packet instead of exhausting memory.
                    return

        sniffer = AsyncSniffer(
            iface=self.config.interface,
            filter=self.config.bpf_filter,
            prn=on_packet,
            store=False,
        )
        sniffer.start()
        try:
            while True:
                yield await queue.get()
        finally:
            sniffer.stop()


class PcapReplayAdapter(PacketCaptureAdapter):
    def __init__(self, config: CaptureConfig) -> None:
        self.config = config

    async def packets(self) -> AsyncIterator[PacketEvent]:
        if not self.config.pcap_file:
            return
        reader = PcapReader(self.config.pcap_file)
        try:
            for pkt in reader:
                event = _convert_packet(pkt)
                if event:
                    yield event
                await asyncio.sleep(0)
        finally:
            reader.close()


class TcpdumpJsonAdapter(PacketCaptureAdapter):
    def __init__(self, config: CaptureConfig) -> None:
        self.config = config

    async def packets(self) -> AsyncIterator[PacketEvent]:
        if not self.config.tcpdump_cmd:
            return
        process = await asyncio.create_subprocess_shell(
            self.config.tcpdump_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            try:
                payload = json.loads(line.decode("utf-8").strip())
            except json.JSONDecodeError:
                continue
            yield PacketEvent(
                timestamp=float(payload.get("timestamp", 0.0)),
                src_ip=str(payload.get("src_ip", "")),
                src_port=int(payload.get("src_port", 0)),
                dst_ip=str(payload.get("dst_ip", "")),
                dst_port=int(payload.get("dst_port", 0)),
                protocol=str(payload.get("protocol", "")),
                payload_size=int(payload.get("payload_size", 0)),
                tcp_flags=payload.get("tcp_flags", {}),
                metadata=payload.get("metadata", {}),
            )


def _convert_packet(pkt) -> PacketEvent | None:
    if not pkt.haslayer(IP):
        return None

    tcp_flags: dict[str, bool] = {}
    src_port = 0
    dst_port = 0
    proto = "IP"
    payload_size = 0
    if pkt.haslayer(TCP):
        tcp_layer = pkt.getlayer(TCP)
        src_port = int(tcp_layer.sport)
        dst_port = int(tcp_layer.dport)
        proto = "TCP"
        payload_size = len(tcp_layer.payload)
        flags = str(tcp_layer.flags)
        tcp_flags = {
            "FIN": "F" in flags,
            "SYN": "S" in flags,
            "RST": "R" in flags,
            "PSH": "P" in flags,
            "ACK": "A" in flags,
            "URG": "U" in flags,
        }
    elif pkt.haslayer(UDP):
        udp_layer = pkt.getlayer(UDP)
        src_port = int(udp_layer.sport)
        dst_port = int(udp_layer.dport)
        proto = "UDP"
        payload_size = len(udp_layer.payload)

    return PacketEvent(
        timestamp=float(pkt.time),
        src_ip=str(pkt.getlayer(IP).src),
        src_port=src_port,
        dst_ip=str(pkt.getlayer(IP).dst),
        dst_port=dst_port,
        protocol=proto,
        payload_size=payload_size,
        tcp_flags=tcp_flags,
        metadata={"capture_engine": "scapy"},
    )

