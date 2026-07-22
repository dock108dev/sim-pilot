from pathlib import Path

import pytest

from sim_pilot.game_bridge import Architecture
from sim_pilot.rail_route.bridge.client import rail_route_bridge_configuration
from sim_pilot.rail_route.bridge.errors import RailRouteBridgeCompatibilityError


def test_configuration_reads_owner_only_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "token"
    token.write_text("x" * 32)
    token.chmod(0o600)
    monkeypatch.setenv("SIM_PILOT_RAIL_ROUTE_BRIDGE_TOKEN_FILE", str(token))
    monkeypatch.setenv("SIM_PILOT_RAIL_ROUTE_BRIDGE_ARCHITECTURE", "arm64")

    configuration = rail_route_bridge_configuration()

    assert configuration.architecture is Architecture.ARM64
    assert configuration.host == "127.0.0.1"
    assert configuration.authentication_token.get_secret_value() == "x" * 32


def test_configuration_rejects_a_permissive_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "token"
    token.write_text("x" * 32)
    token.chmod(0o644)
    monkeypatch.setenv("SIM_PILOT_RAIL_ROUTE_BRIDGE_TOKEN_FILE", str(token))

    with pytest.raises(RailRouteBridgeCompatibilityError, match="not owner-only"):
        rail_route_bridge_configuration()
