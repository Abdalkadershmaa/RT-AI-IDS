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


def test_inference_offloads_lime_explanations(monkeypatch):
    inference = InferenceService(ModelService(model_dir="non-existent-model-dir"))
    monkeypatch.setattr(inference.model_service, "predict", lambda _features: ("Suspicious", 0.9, 0.8))
    monkeypatch.setattr(
        inference.model_service,
        "load",
        lambda: type("Loaded", (), {"explainer": object(), "classifier": object()})(),
    )

    called = {}

    def fake_submit(explainer, classifier, features, flow_id):
        called["args"] = (explainer, classifier, features, flow_id)

    monkeypatch.setattr("services.inference.service.submit_lime_explanation", fake_submit)

    result = inference.classify_flow(flow_id="f2", features=[5.0] * 39, context={})

    assert result.flow_id == "f2"
    assert called["args"][3] == "f2"
