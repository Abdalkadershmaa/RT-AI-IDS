from datetime import datetime, timezone

from .extensions import db


class AttackLog(db.Model):
    __tablename__ = "attack_logs"

    id = db.Column(db.Integer, primary_key=True)
    flow_id = db.Column(db.String(128), nullable=False, index=True)
    source_ip = db.Column(db.String(64), nullable=False, index=True)
    source_port = db.Column(db.Integer, nullable=False)
    destination_ip = db.Column(db.String(64), nullable=False, index=True)
    destination_port = db.Column(db.Integer, nullable=False)
    protocol = db.Column(db.String(16), nullable=False)
    classification = db.Column(db.String(64), nullable=False, index=True)
    probability = db.Column(db.Float, nullable=False)
    risk_label = db.Column(db.String(32), nullable=False, index=True)
    risk_score = db.Column(db.Float, nullable=False)
    rationale = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(tz=timezone.utc),
        nullable=False,
        index=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "flow_id": self.flow_id,
            "source_ip": self.source_ip,
            "source_port": self.source_port,
            "destination_ip": self.destination_ip,
            "destination_port": self.destination_port,
            "protocol": self.protocol,
            "classification": self.classification,
            "probability": self.probability,
            "risk_label": self.risk_label,
            "risk_score": self.risk_score,
            "rationale": self.rationale,
            "created_at": self.created_at.isoformat(),
        }

