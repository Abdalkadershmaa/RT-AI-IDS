import uuid

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from services.inference import InferenceService, ModelService

from ..extensions import db
from ..models import AttackLog

predict_bp = Blueprint("predict", __name__, url_prefix="/api/v1")
inference_service = InferenceService(ModelService())


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@predict_bp.post("/predict")
@jwt_required()
def predict() -> tuple:
    body = request.get_json(silent=True) or {}
    features = body.get("features")
    context = body.get("context", {})
    if not isinstance(features, list) or len(features) != 39:
        return jsonify({"error": "features must be a list of 39 numeric values"}), 400

    try:
        normalized_features = [float(x) for x in features]
    except (TypeError, ValueError):
        return jsonify({"error": "features must contain numeric values"}), 400

    flow_id = str(body.get("flow_id") or uuid.uuid4())
    result = inference_service.classify_flow(
        flow_id=flow_id,
        features=normalized_features,
        context=context if isinstance(context, dict) else {},
    )
    record = AttackLog(
        flow_id=result.flow_id,
        source_ip=str((context or {}).get("src_ip", "")),
        source_port=_safe_int((context or {}).get("src_port", 0)),
        destination_ip=str((context or {}).get("dst_ip", "")),
        destination_port=_safe_int((context or {}).get("dst_port", 0)),
        protocol=str((context or {}).get("protocol", "")),
        classification=result.classification,
        probability=result.probability,
        risk_label=result.risk_label,
        risk_score=result.risk_score,
        rationale=result.rationale,
    )
    db.session.add(record)
    db.session.commit()
    return jsonify(record.to_dict()), 201

