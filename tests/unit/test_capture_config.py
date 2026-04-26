"""Capture configuration plumbing — env vars, CLI flags, interface validation."""

from __future__ import annotations

import argparse

import pytest

from services.ingestion.run_sniffer import _build_config, _validate_interface
from shared.config import reload_settings


def _baseline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", "dev")
    monkeypatch.setenv("JWT_SECRET_KEY", "dev")
    monkeypatch.setenv("ADMIN_PASSWORD", "dev")


def _empty_args() -> argparse.Namespace:
    return argparse.Namespace(
        interface=None,
        bpf_filter=None,
        pcap_file=None,
        tcpdump_cmd=None,
        no_promisc=False,
    )


def test_capture_config_reads_all_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    _baseline_env(monkeypatch)
    monkeypatch.setenv("CAPTURE_INTERFACE", "wlan0")
    monkeypatch.setenv("CAPTURE_BPF_FILTER", "tcp and not port 22")
    monkeypatch.setenv("CAPTURE_PROMISCUOUS", "true")
    reload_settings()

    cfg = _build_config(_empty_args())

    assert cfg.interface == "wlan0"
    assert cfg.bpf_filter == "tcp and not port 22"
    assert cfg.promiscuous is True
    assert cfg.pcap_file is None
    assert cfg.tcpdump_cmd is None


def test_cli_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _baseline_env(monkeypatch)
    monkeypatch.setenv("CAPTURE_INTERFACE", "eth0")
    reload_settings()

    args = _empty_args()
    args.interface = "wlan1"

    cfg = _build_config(args)
    assert cfg.interface == "wlan1"


def test_no_promisc_flag_disables_promiscuous(monkeypatch: pytest.MonkeyPatch) -> None:
    _baseline_env(monkeypatch)
    monkeypatch.setenv("CAPTURE_PROMISCUOUS", "true")
    reload_settings()

    args = _empty_args()
    args.no_promisc = True

    cfg = _build_config(args)
    assert cfg.promiscuous is False


def test_promisc_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _baseline_env(monkeypatch)
    monkeypatch.setenv("CAPTURE_PROMISCUOUS", "false")
    reload_settings()

    cfg = _build_config(_empty_args())
    assert cfg.promiscuous is False


def test_validate_interface_rejects_unknown_name() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        _validate_interface("definitely-not-a-real-iface-xyz")
    assert "not found on this host" in str(excinfo.value)
    assert "Available interfaces" in str(excinfo.value)
