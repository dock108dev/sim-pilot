"""Synchronized Rail Route UI observation and two-cycle route tests."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from sim_pilot.computer_control.backend import CapturedDesktopFrame
from sim_pilot.computer_control.models import (
    ComputerControlCapabilities,
    DesktopFrame,
    InputExecutionResult,
    InputGesture,
    WindowBounds,
)
from sim_pilot.game_bridge.models import (
    Architecture,
    CapabilityManifestPayload,
    CoverageStatus,
    FieldCoverage,
    GameSnapshot,
    Identity,
    IdentityStatus,
    ObservationSurface,
    ObservedEntity,
    Platform,
)
from sim_pilot.rail_route.intent import parse_control_intent
from sim_pilot.rail_route.models import RailRouteInstallation
from sim_pilot.rail_route.ui.controller import execute_set_route_ui
from sim_pilot.rail_route.ui.errors import RailRouteUIObservationError
from sim_pilot.rail_route.ui.models import RailRouteUIScene
from sim_pilot.rail_route.ui.observer import RailRouteUIObserver
from sim_pilot.rail_route.ui.trace import append_ui_trace


def _snapshot(sequence: int, *, route: bool = False) -> GameSnapshot:
    positions = {
        "SIG-C-W": (26, 73),
        "SIG-W-IN": (33, 73),
        "SIG-C-E": (39, 73),
        "SIG-E-IN": (43, 73),
    }
    signals = tuple(
        ObservedEntity(
            entity_type="signal",
            entity_id=name,
            values={
                "allocation_state": "Allocated" if route and name == "SIG-W-IN" else "Free",
                "current_route_to": "26,73|33,73" if route and name == "SIG-W-IN" else None,
                "internal_name": f"Node:Semaphore:{point[0]}:{point[1]}",
                "locked": False,
                "name": name,
                "occupied_train_ids": [],
            },
        )
        for name, point in sorted(positions.items())
    )
    routes = (
        (
            ObservedEntity(
                entity_type="route",
                entity_id="SIG-W-IN",
                values={"destination_connection": "26,73|33,73", "locked": False},
            ),
        )
        if route
        else ()
    )
    surfaces = (
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
                fields=("destination_connection", "locked"),
            ),
            entities=routes,
        ),
        ObservationSurface(
            coverage=FieldCoverage(
                surface="signals",
                status=CoverageStatus.OBSERVED_COMPLETE,
                fields=(
                    "allocation_state",
                    "current_route_to",
                    "internal_name",
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
    )
    return GameSnapshot(
        capture_timestamp=datetime.now(UTC),
        capture_started_marker="main-thread",
        capture_completed_marker="main-thread",
        bridge_sequence=sequence,
        bridge_instance_id="bridge-test",
        game_session_id="session-test",
        game_id="rail-route",
        game_version="2.3.24",
        adapter_version="rail-route-ui-observer-v1",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        map_identity=Identity(
            status=IdentityStatus.OBSERVED,
            value="52da8212-cb1b-44b6-b067-7e7367d02c6c",
            label="Sim Pilot Test Yard",
        ),
        save_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="disposable"),
        game_state={"game_mode": "play", "paused": True},
        surfaces=surfaces,
    )


def _screen(*, changed: bool = False, construction: bool = False) -> Image.Image:
    width, height = 3024, 1964
    image = Image.new("RGB", (width, height), (0, 5, 14))
    draw = ImageDraw.Draw(image)
    center_y = round(height * 0.517)
    for fraction in (0.2865, 0.4995, 0.682, 0.804):
        x = round(width * fraction)
        draw.rectangle((x - 20, center_y - 38, x + 20, center_y - 12), fill=(180, 160, 80))
        draw.rectangle((x - 20, center_y + 12, x + 20, center_y + 38), fill=(180, 160, 80))
    if changed:
        draw.rectangle((1200, 800, 1220, 820), fill=(10, 220, 30))
    if construction:
        draw.line(
            (0, round(height * 0.74), width, round(height * 0.74)), fill=(180, 160, 20), width=4
        )
    return image


class _Discovery:
    def inspect(self) -> RailRouteInstallation:
        return RailRouteInstallation(
            app_path=Path("/Applications/Rail Route.app"),
            executable_path=Path("/Applications/Rail Route.app/Contents/MacOS/Rail Route"),
            version="2.3.24",
            steam_app_id="1124180",
            steam_build_id="22547955",
            process_id=123,
            running=True,
            accessibility_enabled=True,
            supported=True,
            compatibility_reason="compatible",
        )


class _Client:
    def __init__(self, before: GameSnapshot, after: GameSnapshot) -> None:
        self._snapshots = iter((before, after))

    async def connect(self) -> CapabilityManifestPayload:
        return CapabilityManifestPayload(
            observation_surfaces=("game_state", "routes", "signals", "track_occupancy")
        )

    async def request_full_snapshot(self) -> GameSnapshot:
        return next(self._snapshots)

    async def close(self) -> None:
        return None


class _Backend:
    def __init__(self, images: list[Image.Image]) -> None:
        self._images = iter(images)
        self.gestures: list[InputGesture] = []

    def capabilities(self) -> ComputerControlCapabilities:
        return ComputerControlCapabilities(
            platform="macos",
            screen_capture=True,
            accessibility_trusted=True,
            click=True,
            keyboard=True,
            live_verified=True,
            detail="fixture",
        )

    def capture(self, *, process_id: int) -> CapturedDesktopFrame:
        image = next(self._images)
        digest = hashlib.sha256(image.tobytes()).hexdigest()
        metadata = DesktopFrame(
            frame_id=digest,
            captured_at=datetime.now(UTC),
            process_id=process_id,
            window_bounds=WindowBounds(x=0, y=0, width=1512, height=982),
            pixel_width=3024,
            pixel_height=1964,
            display_scale=2.0,
            sha256=digest,
        )
        return CapturedDesktopFrame(metadata, image)

    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> InputExecutionResult:
        assert gesture.expected_frame_id == frame.frame_id
        self.gestures.append(gesture)
        return InputExecutionResult(gesture=gesture, sent_at=datetime.now(UTC))


def _observer(backend: _Backend, clients: list[_Client]) -> RailRouteUIObserver:
    iterator = iter(clients)
    return RailRouteUIObserver(
        backend=backend,
        client_factory=lambda: next(iterator),
        discovery=_Discovery(),  # type: ignore[arg-type]
    )


def test_observer_resolves_four_named_retina_targets() -> None:
    backend = _Backend([_screen()])
    observer = _observer(backend, [_Client(_snapshot(1), _snapshot(2))])

    observed = asyncio.run(observer.observe()).observation

    assert observed.scene is RailRouteUIScene.GAMEPLAY
    assert [target.signal_id for target in observed.signal_targets] == [
        "SIG-C-E",
        "SIG-C-W",
        "SIG-E-IN",
        "SIG-W-IN",
    ]
    west = next(target for target in observed.signal_targets if target.signal_id == "SIG-C-W")
    assert 420 < west.point.x < 460
    assert 490 < west.point.y < 530


def test_observer_rejects_construction_scene_for_mutation() -> None:
    backend = _Backend([_screen(construction=True)])
    observer = _observer(backend, [_Client(_snapshot(1), _snapshot(2))])
    observed = asyncio.run(observer.observe())
    assert observed.observation.scene is RailRouteUIScene.CONSTRUCTION_OPEN


def test_dry_run_sends_no_gesture() -> None:
    backend = _Backend([_screen()])
    observer = _observer(backend, [_Client(_snapshot(1), _snapshot(2))])
    result = asyncio.run(
        execute_set_route_ui(
            parse_control_intent("set a route from SIG-W-IN to SIG-C-W"),
            dry_run=True,
            observer_factory=lambda: observer,
        )
    )
    assert result.verified and result.gestures_sent == 0
    assert backend.gestures == []


def test_route_uses_two_verified_gestures() -> None:
    backend = _Backend([_screen(), _screen(changed=True), _screen(changed=True)])
    clients = [
        _Client(_snapshot(1), _snapshot(2)),
        _Client(_snapshot(3), _snapshot(4)),
        _Client(_snapshot(5, route=True), _snapshot(6, route=True)),
    ]
    observer = _observer(backend, clients)
    result = asyncio.run(
        execute_set_route_ui(
            parse_control_intent("set a route from SIG-W-IN to SIG-C-W"),
            observer_factory=lambda: observer,
        )
    )
    assert result.verified and result.gestures_sent == 2
    assert len(backend.gestures) == 2


def test_unsupported_route_fails_before_observation() -> None:
    backend = _Backend([])
    observer = _observer(backend, [])
    with pytest.raises(RailRouteUIObservationError, match="restricted"):
        asyncio.run(
            execute_set_route_ui(
                parse_control_intent("set a route from SIG-C-W to SIG-W-IN"),
                observer_factory=lambda: observer,
            )
        )


def test_trace_is_owner_only_and_contains_no_screenshot_pixels(tmp_path: Path) -> None:
    backend = _Backend([_screen()])
    observer = _observer(backend, [_Client(_snapshot(1), _snapshot(2))])
    result = asyncio.run(
        execute_set_route_ui(
            parse_control_intent("set a route from SIG-W-IN to SIG-C-W"),
            dry_run=True,
            observer_factory=lambda: observer,
        )
    )
    path = append_ui_trace(result, path=tmp_path / "private" / "traces.jsonl")
    assert path.stat().st_mode & 0o077 == 0
    assert '"gestures_sent":0' in path.read_text()
    assert "image" not in path.read_text()
