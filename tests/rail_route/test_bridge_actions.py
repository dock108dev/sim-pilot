"""Atomic set_route preflight, execution, and verification coverage."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal

import pytest

from sim_pilot.game_bridge import (
    Architecture,
    CapabilityManifestPayload,
    CoverageStatus,
    FieldCoverage,
    GameBridgeConnectionError,
    GameSnapshot,
    Identity,
    IdentityStatus,
    ObservationSurface,
    ObservedEntity,
    Platform,
    SetRouteResponsePayload,
)
from sim_pilot.rail_route.bridge.actions import execute_set_route
from sim_pilot.rail_route.bridge.errors import (
    RailRouteBridgeActionError,
    RailRouteBridgeVerificationError,
)
from sim_pilot.rail_route.intent import parse_control_intent

CONNECTION = "10,10|11,10"


def _snapshot(
    *, sequence: int, route: bool, mode: str = "play", paused: bool = True
) -> GameSnapshot:
    route_entities = (
        (
            ObservedEntity(
                entity_type="route",
                entity_id="SIG-W-IN",
                values={
                    "destination_connection": CONNECTION,
                    "locked": False,
                    "signal_id": "SIG-W-IN",
                },
            ),
        )
        if route
        else ()
    )
    signals = (
        ObservedEntity(
            entity_type="signal",
            entity_id="SIG-C-W",
            values={
                "allocation_state": "Free",
                "current_route_to": None,
                "locked": False,
                "name": "SIG-C-W",
                "occupied_train_ids": [],
            },
        ),
        ObservedEntity(
            entity_type="signal",
            entity_id="SIG-W-IN",
            values={
                "allocation_state": "Allocated" if route else "Free",
                "current_route_to": CONNECTION if route else None,
                "locked": False,
                "name": "SIG-W-IN",
                "occupied_train_ids": [],
            },
        ),
    )
    return GameSnapshot(
        capture_timestamp=datetime.now(UTC),
        capture_started_marker="single-main-thread-sample",
        capture_completed_marker="single-main-thread-sample",
        bridge_sequence=sequence,
        bridge_instance_id="bridge-1",
        game_session_id="session-1",
        game_id="rail-route",
        game_version="2.3.24",
        adapter_version="rail-route-set-route-v1",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        map_identity=Identity(
            status=IdentityStatus.OBSERVED, value="yard", label="Sim Pilot Test Yard"
        ),
        save_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="disposable session"),
        game_state={"game_mode": mode, "paused": paused},
        surfaces=(
            ObservationSurface(
                coverage=FieldCoverage(
                    surface="game_state",
                    status=CoverageStatus.OBSERVED_COMPLETE,
                    fields=("game_mode", "paused"),
                )
            ),
            ObservationSurface(
                coverage=FieldCoverage(
                    surface="routes",
                    status=CoverageStatus.OBSERVED_COMPLETE,
                    fields=("destination_connection", "locked", "signal_id"),
                ),
                entities=route_entities,
            ),
            ObservationSurface(
                coverage=FieldCoverage(
                    surface="signals",
                    status=CoverageStatus.OBSERVED_COMPLETE,
                    fields=(
                        "allocation_state",
                        "current_route_to",
                        "locked",
                        "name",
                        "occupied_train_ids",
                    ),
                ),
                entities=signals,
            ),
            ObservationSurface(
                coverage=FieldCoverage(
                    surface="track_occupancy",
                    status=CoverageStatus.OBSERVED_COMPLETE,
                    fields=("allocation_state",),
                )
            ),
        ),
    )


class _FakeClient:
    def __init__(
        self,
        before: GameSnapshot,
        action: SetRouteResponsePayload,
        after: GameSnapshot,
    ) -> None:
        self.before = before
        self.action = action
        self.after = after
        self.action_calls = 0

    async def connect(self) -> CapabilityManifestPayload:
        return CapabilityManifestPayload(observation_surfaces=("game_state", "routes"))

    async def request_full_snapshot(self) -> GameSnapshot:
        return self.before

    async def request_set_route(self, **_: object) -> tuple[SetRouteResponsePayload, GameSnapshot]:
        self.action_calls += 1
        return self.action, self.after

    async def close(self) -> None:
        return None


def _action(*, outcome: Literal["succeeded", "rejected"] = "succeeded") -> SetRouteResponsePayload:
    return SetRouteResponsePayload(
        origin_signal="SIG-W-IN",
        destination_signal="SIG-C-W",
        destination_connection=CONNECTION if outcome == "succeeded" else None,
        outcome=outcome,
        executed=outcome == "succeeded",
        reason_code="ok" if outcome == "succeeded" else "occupied_path",
        detail="fixture result",
    )


def test_set_route_executes_once_and_verifies_fresh_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        _snapshot(sequence=3, route=False), _action(), _snapshot(sequence=5, route=True)
    )
    monkeypatch.setattr(
        "sim_pilot.rail_route.bridge.actions.rail_route_bridge_client", lambda: client
    )

    result = asyncio.run(
        execute_set_route(parse_control_intent("set a route from SIG-W-IN to SIG-C-W"))
    )

    assert result.verified
    assert client.action_calls == 1
    assert "set once" in result.message


def test_set_route_fails_before_execution_on_wrong_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        _snapshot(sequence=3, route=False, mode="editor"),
        _action(),
        _snapshot(sequence=5, route=True),
    )
    monkeypatch.setattr(
        "sim_pilot.rail_route.bridge.actions.rail_route_bridge_client", lambda: client
    )

    with pytest.raises(RailRouteBridgeActionError, match="play mode"):
        asyncio.run(execute_set_route(parse_control_intent("set a route from SIG-W-IN to SIG-C-W")))
    assert client.action_calls == 0


def test_set_route_fails_before_execution_when_session_is_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        _snapshot(sequence=3, route=False, paused=False),
        _action(),
        _snapshot(sequence=5, route=True),
    )
    monkeypatch.setattr(
        "sim_pilot.rail_route.bridge.actions.rail_route_bridge_client", lambda: client
    )

    with pytest.raises(RailRouteBridgeActionError, match="paused"):
        asyncio.run(execute_set_route(parse_control_intent("set a route from SIG-W-IN to SIG-C-W")))
    assert client.action_calls == 0


def test_set_route_never_retries_when_fresh_snapshot_misses_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        _snapshot(sequence=3, route=False),
        _action(),
        _snapshot(sequence=5, route=False),
    )
    monkeypatch.setattr(
        "sim_pilot.rail_route.bridge.actions.rail_route_bridge_client", lambda: client
    )

    with pytest.raises(RailRouteBridgeVerificationError, match="no retry"):
        asyncio.run(execute_set_route(parse_control_intent("set a route from SIG-W-IN to SIG-C-W")))
    assert client.action_calls == 1


def test_set_route_never_retries_when_connection_fails_after_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        _snapshot(sequence=3, route=False),
        _action(),
        _snapshot(sequence=5, route=True),
    )

    async def disconnect(**_: object) -> tuple[SetRouteResponsePayload, GameSnapshot]:
        client.action_calls += 1
        raise GameBridgeConnectionError("fixture disconnect")

    monkeypatch.setattr(client, "request_set_route", disconnect)
    monkeypatch.setattr(
        "sim_pilot.rail_route.bridge.actions.rail_route_bridge_client", lambda: client
    )

    with pytest.raises(RailRouteBridgeVerificationError, match="no retry"):
        asyncio.run(execute_set_route(parse_control_intent("set a route from SIG-W-IN to SIG-C-W")))
    assert client.action_calls == 1
