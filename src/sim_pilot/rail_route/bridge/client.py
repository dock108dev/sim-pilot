"""Rail Route composition for the capability-gated game bridge client."""

from __future__ import annotations

import os
import platform as host_platform
import stat
from pathlib import Path

from pydantic import SecretStr, ValidationError

from sim_pilot.game_bridge import (
    Architecture,
    GameBridgeClient,
    GameBridgeConfiguration,
    Platform,
)

from .errors import RailRouteBridgeCompatibilityError
from .installer import DEFAULT_STATE_DIRECTORY

RAIL_ROUTE_ADAPTER_VERSION = "rail-route-ui-observer-v1"
RAIL_ROUTE_GAME_ID = "rail-route"
RAIL_ROUTE_GAME_VERSION = "2.3.24"
DEFAULT_PORT = 18461


def _positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise RailRouteBridgeCompatibilityError(f"{name} must be a number") from error
    if value <= 0:
        raise RailRouteBridgeCompatibilityError(f"{name} must be positive")
    return value


def rail_route_bridge_configuration() -> GameBridgeConfiguration:
    token_path = Path(
        os.environ.get(
            "SIM_PILOT_RAIL_ROUTE_BRIDGE_TOKEN_FILE",
            str(DEFAULT_STATE_DIRECTORY / "auth-token"),
        )
    )
    if not token_path.is_file() or token_path.is_symlink():
        raise RailRouteBridgeCompatibilityError(
            f"owner-only bridge authentication token not found at {token_path}"
        )
    if stat.S_IMODE(token_path.stat().st_mode) & 0o077:
        raise RailRouteBridgeCompatibilityError("bridge authentication token is not owner-only")
    token = token_path.read_text().strip()
    try:
        port = int(os.environ.get("SIM_PILOT_RAIL_ROUTE_BRIDGE_PORT", str(DEFAULT_PORT)))
        maximum = int(
            os.environ.get("SIM_PILOT_RAIL_ROUTE_BRIDGE_MAXIMUM_MESSAGE_BYTES", "1048576")
        )
    except ValueError as error:
        raise RailRouteBridgeCompatibilityError(
            "bridge port and maximum message bytes must be integers"
        ) from error
    expected_architecture = os.environ.get("SIM_PILOT_RAIL_ROUTE_BRIDGE_ARCHITECTURE", "x86_64")
    try:
        architecture = Architecture(expected_architecture)
    except ValueError as error:
        raise RailRouteBridgeCompatibilityError(
            "SIM_PILOT_RAIL_ROUTE_BRIDGE_ARCHITECTURE must be x86_64 or arm64"
        ) from error
    system = host_platform.system()
    bridge_platform = Platform.MACOS if system == "Darwin" else Platform.WINDOWS
    try:
        return GameBridgeConfiguration(
            port=port,
            authentication_token=SecretStr(token),
            expected_adapter_version=RAIL_ROUTE_ADAPTER_VERSION,
            expected_game_id=RAIL_ROUTE_GAME_ID,
            expected_game_version=RAIL_ROUTE_GAME_VERSION,
            platform=bridge_platform,
            architecture=architecture,
            connect_timeout_seconds=_positive_float(
                "SIM_PILOT_RAIL_ROUTE_BRIDGE_CONNECTION_TIMEOUT_SECONDS", 5.0
            ),
            read_timeout_seconds=_positive_float(
                "SIM_PILOT_RAIL_ROUTE_BRIDGE_READ_TIMEOUT_SECONDS", 5.0
            ),
            maximum_message_bytes=maximum,
        )
    except ValidationError as error:
        raise RailRouteBridgeCompatibilityError(
            "Rail Route bridge configuration is invalid"
        ) from error


def rail_route_bridge_client() -> GameBridgeClient:
    return GameBridgeClient(rail_route_bridge_configuration())
