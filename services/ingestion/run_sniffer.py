import argparse
import asyncio
import logging

from shared.config import get_settings
from shared.logging_utils import configure_logging

from .publisher import RedisPublisher
from .sniffer import CaptureConfig, PcapReplayAdapter, ScapyLiveAdapter, TcpdumpJsonAdapter

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Async IDS packet ingestion service")
    parser.add_argument("--interface", type=str, default=None)
    parser.add_argument("--bpf-filter", type=str, default=None)
    parser.add_argument("--pcap-file", type=str, default=None)
    parser.add_argument("--tcpdump-cmd", type=str, default=None)
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

    async for packet in adapter.packets():
        await publisher.publish(packet)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("ingestion_service_stopped")

