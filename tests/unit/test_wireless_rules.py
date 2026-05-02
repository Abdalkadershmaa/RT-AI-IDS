from services.inference.wireless_rules import evaluate_wireless_findings


def test_wireless_rules_ignores_non_wifi_metadata():
    findings = evaluate_wireless_findings({"link_type": "ethernet"})
    assert findings == []


def test_wireless_rules_flags_wep_and_wps_indicators():
    findings = evaluate_wireless_findings(
        {
            "link_type": "802.11",
            "privacy_wep_enabled": True,
            "wps_enabled": True,
            "wps_failed_enrollment_attempts": 5,
        }
    )
    assert "legacy_wep_exposure_indicator" in findings
    assert "wps_exposure_or_bruteforce_indicator" in findings

