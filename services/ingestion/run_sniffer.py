"""Ingestion service entrypoint.

Selects a capture adapter (live interface, PCAP replay, tcpdump JSON) based
on CLI flags, then forwards every captured :class:`PacketEvent` to the Redis
Streams broker.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from shared.config import get_settings
from shared.observability import configure_logging

from .publisher import RedisPublisher
from .sniffer import CaptureConfig, PcapReplayAdapter, ScapyLiveAdapter, TcpdumpJsonAdapter

logger = logging.getLogger(__name__)

DROP_LOG_INTERVAL = 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Async IDS packet ingestion service")
    parser.add_argument("--interface", type=str, default=None, help="Live interface name")
    parser.add_argument("--bpf-filter", type=str, default=None, help="Berkeley Packet Filter")
    parser.add_argument("--pcap-file", type=str, default=None, help="PCAP file to replay")
    parser.add_argument(
        "--tcpdump-cmd",
        type=str,
        default=None,
        help="Shell command emitting per-line JSON packet records",
    )
    return parser.parse_args()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    args = parse_args()
    config = CaptureConfig(
        interface=args.interface,
        bpf_filter=args.bpf_filter,
        pcap_file=args.pcap_file,
        tcpdump_cmd=args.tcpdump_cmd,
    )
    publisher = RedisPublisher()
    if config.tcpdump_cmd:
        adapter = TcpdumpJsonAdapter(config)
    elif config.pcap_file:
        adapter = PcapReplayAdapter(config)
    else:
        adapter = ScapyLiveAdapter(config)

    last_logged_drops = 0
    try:
        async for packet in adapter.packets():
            await publisher.publish(packet)
            adapter_drops = getattr(adapter, "dropped", 0)
            if adapter_drops - last_logged_drops >= DROP_LOG_INTERVAL:
                logger.warning(
                    "ingestion_drops_observed",
                    extra={"dropped_total": adapter_drops},
                )
                last_logged_drops = adapter_drops
    finally:
        await publisher.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("ingestion_service_stopped")
