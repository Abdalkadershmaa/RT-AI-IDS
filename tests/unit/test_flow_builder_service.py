from services.flow_builder.service import FlowBuilderService
from shared.schemas import PacketEvent


def _packet(timestamp: float, src_port: int = 1111, dst_port: int = 80) -> PacketEvent:
    return PacketEvent(
        timestamp=timestamp,
        src_ip="10.0.0.1",
        src_port=src_port,
        dst_ip="10.0.0.2",
        dst_port=dst_port,
        protocol="TCP",
        payload_size=50,
        tcp_flags={"ACK": True},
        metadata={},
    )


def test_flow_builder_limits_open_flow_count():
    service = FlowBuilderService(flow_timeout_seconds=600, max_flows=1)
    service.process_packet(_packet(1.0, src_port=1001))
    service.process_packet(_packet(2.0, src_port=1002))
    assert len(service.current_flows) == 1


def test_flow_builder_emits_flow_event_on_termination():
    service = FlowBuilderService(flow_timeout_seconds=600, max_flows=100)
    service.process_packet(_packet(1.0))
    fin_packet = PacketEvent(
        timestamp=2.0,
        src_ip="10.0.0.1",
        src_port=1111,
        dst_ip="10.0.0.2",
        dst_port=80,
        protocol="TCP",
        payload_size=80,
        tcp_flags={"FIN": True},
        metadata={},
    )
    events = service.process_packet(fin_packet)
    assert len(events) == 1
    assert events[0].context["src_ip"] == "10.0.0.1"

