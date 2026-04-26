from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class PacketEvent:
    timestamp: float
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    protocol: str
    payload_size: int
    tcp_flags: dict[str, bool]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FlowFeatureEvent:
    flow_id: str
    features: list[float]
    context: dict[str, Any]
    observed_at: str

    @classmethod
    def build(cls, flow_id: str, features: list[float], context: dict[str, Any]) -> "FlowFeatureEvent":
        return cls(
            flow_id=flow_id,
            features=features,
            context=context,
            observed_at=datetime.now(tz=UTC).isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DetectionResult:
    flow_id: str
    classification: str
    probability: float
    risk_label: str
    risk_score: float
    rationale: list[str]
    observed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

