from typing import Any


def evaluate_wireless_findings(metadata: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    proto = (metadata.get("link_type") or "").lower()
    if "802.11" not in proto and "wifi" not in proto:
        return findings

    management_burst = int(metadata.get("mgmt_frame_burst_count", 0))
    if management_burst >= 40:
        findings.append("suspicious_management_frame_burst")

    deauth_count = int(metadata.get("deauth_frame_count", 0))
    if deauth_count >= 10:
        findings.append("possible_deauth_flood_detected")

    akm = str(metadata.get("akm_suite", "")).lower()
    if "wep" in akm or metadata.get("privacy_wep_enabled") is True:
        findings.append("legacy_wep_exposure_indicator")

    wps_enabled = bool(metadata.get("wps_enabled", False))
    wps_pbc = bool(metadata.get("wps_push_button_mode", False))
    wps_failed = int(metadata.get("wps_failed_enrollment_attempts", 0))
    if wps_enabled and (wps_pbc or wps_failed >= 3):
        findings.append("wps_exposure_or_bruteforce_indicator")

    return findings

