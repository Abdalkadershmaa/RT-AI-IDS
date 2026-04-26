"""Flow builder.

Aggregates :class:`PacketEvent` records into directional flows and emits a
:class:`FlowFeatureEvent` when a flow terminates (TCP FIN/RST or idle
timeout). Flow tracking is bounded both by ``flow_timeout_seconds`` (idle
expiration) and ``max_flows`` (hard cap).

The eviction structure is an :class:`OrderedDict` ordered by last-seen
timestamp, which gives O(1) amortized eviction in place of the previous O(N)
``min(...)`` scan over the full dict.

.. note::

    The legacy :mod:`flow.Flow` feature extractor inherited a copy-paste bug
    from upstream (``setFwdPSHFlags`` is set from ``getURGFlag`` rather than
    ``getPSHFlag``). The current saved model was likely trained on the buggy
    feature so we *do not* fix it here. See ``Q1`` in ``docs/architecture.md``
    and the TODO comment in ``flow/Flow.py``.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

from flow.Flow import Flow
from flow.PacketInfo import PacketInfo
from shared.schemas import FlowFeatureEvent, PacketEvent

logger = logging.getLogger(__name__)


class FlowBuilderService:
    """Stateful aggregator. Not thread-safe; one instance per worker process."""

    def __init__(self, flow_timeout_seconds: int = 600, max_flows: int = 50_000) -> None:
        self.flow_timeout_seconds = flow_timeout_seconds
        self.max_flows = max_flows
        # Ordered insertion + move_to_end on touch ⇒ head is the LRU candidate.
        self.current_flows: OrderedDict[str, Flow] = OrderedDict()
        self._packets_seen = 0

    def process_packet(self, packet_event: PacketEvent) -> list[FlowFeatureEvent]:
        """Update flow state for ``packet_event``; return any terminated flows."""

        self._packets_seen += 1
        if self._packets_seen % 1000 == 0:
            self._evict_stale_flows(packet_event.timestamp)
        packet = self._packet_info_from_event(packet_event)
        output: list[FlowFeatureEvent] = []
        fwd_id = packet.getFwdID()
        bwd_id = packet.getBwdID()
        active_key = (
            fwd_id
            if fwd_id in self.current_flows
            else bwd_id
            if bwd_id in self.current_flows
            else None
        )

        if active_key is None:
            if len(self.current_flows) >= self.max_flows:
                self._evict_oldest_flow()
            self.current_flows[fwd_id] = Flow(packet)
            return output

        flow = self.current_flows[active_key]
        direction = "fwd" if active_key == fwd_id else "bwd"
        timed_out = (packet.getTimestamp() - flow.getFlowLastSeen()) > self.flow_timeout_seconds
        terminated = packet.getFINFlag() or packet.getRSTFlag()

        if timed_out or terminated:
            features = flow.terminated()
            output.append(
                FlowFeatureEvent.build(
                    flow_id=active_key,
                    features=[
                        float(x) if isinstance(x, int | float) else 0.0 for x in features[:39]
                    ],
                    context={
                        "src_ip": packet_event.src_ip,
                        "src_port": packet_event.src_port,
                        "dst_ip": packet_event.dst_ip,
                        "dst_port": packet_event.dst_port,
                        "protocol": packet_event.protocol,
                        "wireless": packet_event.metadata.get("wireless", {}),
                    },
                )
            )
            self.current_flows.pop(active_key, None)
            if not terminated:
                self.current_flows[fwd_id] = Flow(packet)
            return output

        flow.new(packet, direction)
        # Refresh LRU position so eviction prefers truly idle flows.
        self.current_flows.move_to_end(active_key)
        return output

    def _evict_stale_flows(self, now: float) -> None:
        """Drop flows whose last-seen timestamp is older than the timeout."""

        threshold = now - self.flow_timeout_seconds
        stale: list[str] = []
        for key, flow in self.current_flows.items():
            if flow.getFlowLastSeen() <= threshold:
                stale.append(key)
            else:
                # OrderedDict + move_to_end guarantees insertion order is
                # roughly LRU; once we hit a fresh entry every later entry is
                # at least as fresh.
                break
        for key in stale:
            self.current_flows.pop(key, None)
        if stale:
            logger.debug("flow_builder_evicted_stale count=%d", len(stale))

    def _evict_oldest_flow(self) -> None:
        """Drop the LRU flow. O(1)."""

        if not self.current_flows:
            return
        self.current_flows.popitem(last=False)

    def _packet_info_from_event(self, event: PacketEvent) -> PacketInfo:
        packet = PacketInfo()
        packet.src = event.src_ip
        packet.dest = event.dst_ip
        packet.src_port = event.src_port
        packet.dest_port = event.dst_port
        packet.protocol = event.protocol
        packet.timestamp = event.timestamp
        packet.payload_bytes = event.payload_size
        packet.packet_size = event.payload_size
        packet.header_bytes = 0
        packet.FIN_flag = bool(event.tcp_flags.get("FIN", False))
        packet.SYN_flag = bool(event.tcp_flags.get("SYN", False))
        packet.RST_flag = bool(event.tcp_flags.get("RST", False))
        packet.PSH_flag = bool(event.tcp_flags.get("PSH", False))
        packet.ACK_flag = bool(event.tcp_flags.get("ACK", False))
        packet.URG_flag = bool(event.tcp_flags.get("URG", False))
        packet.win_bytes = 0
        packet.setFwdID()
        packet.setBwdID()
        return packet
