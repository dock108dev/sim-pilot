from __future__ import annotations

import asyncio
import subprocess

import pytest
from pydantic import SecretStr

from sim_pilot.game_bridge import Architecture, GameBridgeConfiguration, Platform
from sim_pilot.software_inc.bridge.client import SoftwareIncBridgeClient
from sim_pilot.software_inc.bridge.foreground import foreground_running_software_inc
from sim_pilot.software_inc.errors import SoftwareIncForegroundError


def _configuration() -> GameBridgeConfiguration:
    return GameBridgeConfiguration(
        port=18462,
        authentication_token=SecretStr("a" * 32),
        expected_adapter_version="software-inc-readonly-v9",
        expected_game_id="software-inc",
        expected_game_version="1.8.41",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
    )


def test_operation_begins_before_game_is_foregrounded() -> None:
    events: list[str] = []

    def foreground() -> None:
        events.append("foreground")

    async def exercise() -> str:
        class TestClient(SoftwareIncBridgeClient):
            async def run_with_foreground(self) -> str:
                async def operation() -> str:
                    events.append("request_started")
                    while "foreground" not in events:
                        await asyncio.sleep(0)
                    events.append("response_received")
                    return "snapshot"

                return await self._while_game_is_foreground(operation())

        client = TestClient(_configuration(), foreground=foreground)
        return await client.run_with_foreground()

    assert asyncio.run(exercise()) == "snapshot"
    assert events == ["request_started", "foreground", "response_received"]


def test_foreground_targets_existing_exact_bundle_without_apple_events_or_opening_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def run(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)

    foreground_running_software_inc()

    assert captured[0][:4] == ["/usr/bin/osascript", "-l", "JavaScript", "-e"]
    assert "unity.Coredumping.Software Inc" in captured[0][4]
    assert "NSRunningApplication" in captured[0][4]
    assert "System Events" not in captured[0][4]
    assert "/usr/bin/open" not in captured[0]


def test_foreground_failure_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 1, "", "process is not running")

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(SoftwareIncForegroundError, match="process is not running"):
        foreground_running_software_inc()
