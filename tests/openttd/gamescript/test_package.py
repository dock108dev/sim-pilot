"""Static contract checks for the separately installed OpenTTD package."""

from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).parents[3] / "openttd_gamescript" / "sim_pilot_bridge"


def test_package_declares_the_verified_openttd_api_and_protocol() -> None:
    info = (PACKAGE / "info.nut").read_text(encoding="utf-8")
    main = (PACKAGE / "main.nut").read_text(encoding="utf-8")

    assert 'GetName() { return "SimPilotBridge"; }' in info
    assert 'GetAPIVersion() { return "15"; }' in info
    assert "protocol_version = 2;" in main
    assert "ledger_limit = 64;" in main
    assert '"set_company_name"' in main
    assert '"world_manifest"' in main
    assert '"world_collection_page"' in main
    assert "c7e830e62f9898d01704396f91785c9e4a6e9abf87cc08799f8f49a4d4103ec6" in main
    assert "function HasExactKeys(value, keys)" in main


def test_package_does_not_advertise_unverified_actions_or_deltas() -> None:
    main = (PACKAGE / "main.nut").read_text(encoding="utf-8")

    assert "state_deltas = false" in main
    assert 'supported_actions = ["set_company_name"]' in main
    for unsupported in ("build_road", "build_rail", "build_station", "buy_vehicle"):
        assert unsupported not in main
