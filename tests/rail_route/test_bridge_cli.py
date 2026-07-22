from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from sim_pilot.cli import app
from sim_pilot.game_bridge.models import (
    BridgeEnvelope,
    CapabilityManifestPayload,
    FullSnapshotResponsePayload,
    GameSnapshot,
    parse_envelope,
)
from sim_pilot.rail_route.models import RailRouteAction, RailRouteIntent


def _fixture(name: str) -> BridgeEnvelope:
    return parse_envelope(Path(f"tests/fixtures/game_bridge/v2/{name}.json").read_bytes())


def test_bridge_capabilities_command_advertises_only_set_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fixture("capability_manifest").payload
    assert isinstance(payload, CapabilityManifestPayload)

    async def capabilities() -> CapabilityManifestPayload:
        return payload

    monkeypatch.setattr("sim_pilot.cli._rail_route_bridge_capabilities_async", capabilities)

    result = CliRunner().invoke(app, ["rail-route", "bridge", "capabilities"])

    assert result.exit_code == 0
    assert '"set_route"' in result.stdout


def test_bridge_observe_command_renders_typed_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fixture("full_snapshot_response").payload
    assert isinstance(payload, FullSnapshotResponsePayload)

    async def observe() -> GameSnapshot:
        return payload.snapshot

    monkeypatch.setattr("sim_pilot.cli._rail_route_bridge_observe_async", observe)

    result = CliRunner().invoke(app, ["rail-route", "bridge", "observe"])

    assert result.exit_code == 0
    assert "game_state=observed_complete" in result.stdout
    assert "trains=observed_partial" in result.stdout


def test_bridge_list_and_show_commands_query_observed_entities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fixture("full_snapshot_response").payload
    assert isinstance(payload, FullSnapshotResponsePayload)

    async def observe() -> GameSnapshot:
        return payload.snapshot

    monkeypatch.setattr("sim_pilot.cli._rail_route_bridge_observe_async", observe)

    listed = CliRunner().invoke(app, ["rail-route", "bridge", "list", "trains"])
    shown = CliRunner().invoke(app, ["rail-route", "bridge", "show", "trains", "SP 101"])

    assert listed.exit_code == 0
    assert "train:1 — SP 101" in listed.stdout
    assert shown.exit_code == 0
    assert '"display_name": "SP 101"' in shown.stdout


def test_plain_english_do_dispatches_only_atomic_set_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[RailRouteIntent] = []

    async def execute(intent: RailRouteIntent) -> SimpleNamespace:
        seen.append(intent)
        return SimpleNamespace(message="verified route fixture")

    monkeypatch.setattr("sim_pilot.cli.execute_set_route", execute)

    result = CliRunner().invoke(
        app,
        ["rail-route", "do", "set a route from SIG-W-IN to SIG-C-W"],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "verified route fixture"
    assert seen[0].action is RailRouteAction.SET_ROUTE
    assert seen[0].origin_signal == "SIG-W-IN"
    assert seen[0].destination_signal == "SIG-C-W"
