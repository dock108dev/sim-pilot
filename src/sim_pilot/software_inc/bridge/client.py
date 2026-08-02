"""Software Inc. composition for Game Bridge Protocol v3."""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

from pydantic import SecretStr

from sim_pilot.game_bridge import (
    Architecture,
    CapabilityManifestPayload,
    ClientState,
    GameBridgeClient,
    GameBridgeConfiguration,
    GameSnapshot,
    Platform,
)
from sim_pilot.software_inc.errors import SoftwareIncCompatibilityError

from .foreground import foreground_running_software_inc
from .installer import DEFAULT_STATE_DIRECTORY

ADAPTER_VERSION = "software-inc-readonly-v10"
GAME_ID = "software-inc"
GAME_VERSION = "1.8.41"
DEFAULT_PORT = 18462
ResultT = TypeVar("ResultT")


class SoftwareIncBridgeClient(GameBridgeClient):
    """Bridge client that lets Unity service requests while Terminal owns focus."""

    def __init__(
        self,
        configuration: GameBridgeConfiguration,
        *,
        foreground: Callable[[], None] = foreground_running_software_inc,
    ) -> None:
        super().__init__(configuration)
        self._foreground = foreground

    async def connect(self) -> CapabilityManifestPayload:
        if self.capabilities is not None and self.state is ClientState.SYNCHRONIZED:
            return self.capabilities
        return await self._while_game_is_foreground(super().connect())

    async def request_full_snapshot(self) -> GameSnapshot:
        return await self._while_game_is_foreground(super().request_full_snapshot())

    async def _while_game_is_foreground(self, operation: Awaitable[ResultT]) -> ResultT:
        request = asyncio.ensure_future(operation)
        await asyncio.sleep(0)
        try:
            await asyncio.to_thread(self._foreground)
        except Exception:
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
            raise
        return await request


def software_inc_bridge_configuration() -> GameBridgeConfiguration:
    token_path = Path(
        os.environ.get(
            "SIM_PILOT_SOFTWARE_INC_BRIDGE_TOKEN_FILE", str(DEFAULT_STATE_DIRECTORY / "auth-token")
        )
    )
    if (
        token_path.is_symlink()
        or not token_path.is_file()
        or stat.S_IMODE(token_path.stat().st_mode) & 0o077
    ):
        raise SoftwareIncCompatibilityError(f"owner-only bridge token not found at {token_path}")
    try:
        port = int(os.environ.get("SIM_PILOT_SOFTWARE_INC_BRIDGE_PORT", str(DEFAULT_PORT)))
    except ValueError as error:
        raise SoftwareIncCompatibilityError("bridge port must be an integer") from error
    return GameBridgeConfiguration(
        port=port,
        authentication_token=SecretStr(token_path.read_text().strip()),
        expected_adapter_version=ADAPTER_VERSION,
        expected_game_id=GAME_ID,
        expected_game_version=GAME_VERSION,
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        connect_timeout_seconds=5.0,
        read_timeout_seconds=5.0,
    )


def software_inc_bridge_client() -> SoftwareIncBridgeClient:
    return SoftwareIncBridgeClient(software_inc_bridge_configuration())
