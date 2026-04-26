"""Ingestion service entrypoint.

Selects a capture adapter (live interface, PCAP replay, tcpdump JSON) based
on configuration, then forwards every captured :class:`PacketEvent` to the
Redis Streams broker.

Configuration precedence (highest first):

1. Command-line flags (``--interface``, ``--bpf-filter``, …).
2. Environment variables surfaced through :class:`shared.config.Settings`
   (``CAPTURE_INTERFACE``, ``CAPTURE_BPF_FILTER``, ``CAPTURE_PROMISCUOUS``,
   ``CAPTURE_PCAP_FILE``, ``CAPTURE_CMD``).
3. Built-in defaults.

If a live interface is requested, the name is validated against the kernel's
list of interfaces before sniffing begins. If the interface does not exist
the service exits with a clear error listing the available names.
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
    parser.add_argument(
        "--interface",
        type=str,
        default=None,
        help="Live interface name (overrides CAPTURE_INTERFACE env var)",
    )
    parser.add_argument(
        "--bpf-filter",
        type=str,
        default=None,
        help="Berkeley Packet Filter (overrides CAPTURE_BPF_FILTER env var)",
    )
    parser.add_argument(
        "--pcap-file",
        type=str,
        default=None,
        help="PCAP file to replay (overrides CAPTURE_PCAP_FILE env var)",
    )
    parser.add_argument(
        "--tcpdump-cmd",
        type=str,
        default=None,
        help="Shell command emitting per-line JSON packet records (overrides CAPTURE_CMD)",
    )
    parser.add_argument(
        "--no-promisc",
        action="store_true",
        help="Disable promiscuous mode (default: enabled)",
    )
    return parser.parse_args()


def _list_available_interfaces() -> list[str]:
    """Return the kernel's interface names. Best-effort, non-fatal."""

    try:
        from scapy.all import get_if_list  # type: ignore

        return [str(name) for name in get_if_list()]
    except Exception as exc:  # pragma: no cover - depends on host
        logger.debug("could_not_list_interfaces error=%s", exc)
        return []


def _validate_interface(interface: str) -> None:
    """Raise ``RuntimeError`` if ``interface`` is not present on the host."""

    available = _list_available_interfaces()
    if not available:
        # Could not enumerate (e.g. minimal container without /proc/net/dev).
        # Don't block startup — let scapy raise a more specific error if any.
        logger.warning(
            "capture_interface_validation_skipped",
            extra={"interface": interface, "reason": "no interface list available"},
        )
        return
    if interface not in available:
        raise RuntimeError(
            f"CAPTURE_INTERFACE='{interface}' not found on this host. "
            f"Available interfaces: {', '.join(available) or '(none detected)'}"
        )


def _build_config(args: argparse.Namespace) -> CaptureConfig:
    settings = get_settings()
    return CaptureConfig(
        interface=args.interface or settings.capture_interface,
        bpf_filter=args.bpf_filter or settings.capture_bpf_filter,
        pcap_file=args.pcap_file or settings.capture_pcap_file,
        tcpdump_cmd=args.tcpdump_cmd or settings.capture_tcpdump_cmd,
        promiscuous=(not args.no_promisc) and settings.capture_promiscuous,
    )


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    args = parse_args()
    config = _build_config(args)
    publisher = RedisPublisher()

    if config.tcpdump_cmd:
        mode = "tcpdump_subprocess"
        adapter: PcapReplayAdapter | ScapyLiveAdapter | TcpdumpJsonAdapter = TcpdumpJsonAdapter(
            config
        )
    elif config.pcap_file:
        mode = "pcap_replay"
        adapter = PcapReplayAdapter(config)
    else:
        if not config.interface:
            raise RuntimeError(
                "no capture source configured. Set CAPTURE_INTERFACE (live sniff), "
                "CAPTURE_PCAP_FILE (replay), or CAPTURE_CMD (tcpdump JSON)."
            )
        _validate_interface(config.interface)
        mode = "scapy_live"
        adapter = ScapyLiveAdapter(config)

    logger.info(
        "ingestion_capture_starting",
        extra={
            "mode": mode,
            "interface": config.interface,
            "bpf_filter": config.bpf_filter,
            "pcap_file": config.pcap_file,
            "promiscuous": config.promiscuous,
        },
    )

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
