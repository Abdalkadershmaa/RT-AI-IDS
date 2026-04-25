from services.inference.model_service import ModelService
from services.inference.service import InferenceService


def test_model_service_loads_once():
    service = ModelService(model_dir="non-existent-model-dir")
    first = service.load()
    second = service.load()
    assert first is second


def test_inference_rationale_includes_wireless_findings():
    inference = InferenceService(ModelService(model_dir="non-existent-model-dir"))
    result = inference.classify_flow(
        flow_id="f1",
        features=[5.0] * 39,
        context={
            "wireless": {
                "link_type": "wifi",
                "mgmt_frame_burst_count": 50,
                "deauth_frame_count": 12,
                "privacy_wep_enabled": True,
                "wps_enabled": True,
                "wps_push_button_mode": True,
            }
        },
    )
    assert result.flow_id == "f1"
    assert "suspicious_management_frame_burst" in result.rationale
    assert "legacy_wep_exposure_indicator" in result.rationale

