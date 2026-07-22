"""Synchronized screenshot and semantic observation for the canonical Test Yard."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Protocol, cast

from PIL import Image

from sim_pilot.computer_control.backend import CapturedDesktopFrame, ComputerControlBackend
from sim_pilot.computer_control.backends.macos import MacOSComputerControlBackend
from sim_pilot.computer_control.models import ScreenPoint
from sim_pilot.game_bridge.models import CapabilityManifestPayload, CoverageStatus, GameSnapshot
from sim_pilot.rail_route.bridge.client import rail_route_bridge_client
from sim_pilot.rail_route.bridge.query import surface_from
from sim_pilot.rail_route.discovery import RailRouteDiscovery
from sim_pilot.rail_route.ui.errors import RailRouteUIObservationError
from sim_pilot.rail_route.ui.models import (
    RailRouteUICapabilities,
    RailRouteUIObservation,
    RailRouteUIScene,
    SignalScreenTarget,
)

TEST_YARD_MAP_ID = "52da8212-cb1b-44b6-b067-7e7367d02c6c"
TEST_YARD_LABEL = "Sim Pilot Test Yard"
TEST_YARD_ROUTE = ("SIG-W-IN", "SIG-C-W")
_SIGNAL_NAME = re.compile(r"^Node:Semaphore:(?P<x>-?\d+):(?P<y>-?\d+)$")


class ObservedRailRouteUI:
    def __init__(self, observation: RailRouteUIObservation, capture: CapturedDesktopFrame) -> None:
        self.observation = observation
        self.capture = capture


class BridgeObservationClient(Protocol):
    async def connect(self) -> CapabilityManifestPayload: ...

    async def request_full_snapshot(self) -> GameSnapshot: ...

    async def close(self) -> None: ...


class RailRouteUIObserver:
    def __init__(
        self,
        *,
        backend: ComputerControlBackend | None = None,
        client_factory: Callable[[], BridgeObservationClient] = rail_route_bridge_client,
        discovery: RailRouteDiscovery | None = None,
    ) -> None:
        self.backend = backend or MacOSComputerControlBackend("Rail Route")
        self._client_factory = client_factory
        self._discovery = discovery or RailRouteDiscovery()

    async def observe(self) -> ObservedRailRouteUI:
        installation = self._discovery.inspect()
        if not installation.supported or installation.process_id is None:
            raise RailRouteUIObservationError(installation.compatibility_reason)
        client = self._client_factory()
        try:
            capabilities = await client.connect()
            if capabilities.gameplay_actions:
                raise RailRouteUIObservationError(
                    "production bridge must advertise an empty gameplay-action catalog"
                )
            before = await client.request_full_snapshot()
            capture = self.backend.capture(process_id=installation.process_id)
            after = await client.request_full_snapshot()
        finally:
            await client.close()
        _require_continuity(before, after)
        targets = _resolve_test_yard_targets(after, capture)
        scene = _classify_scene(capture.image)
        projection = _projection_id(capture, targets)
        observation = RailRouteUIObservation(
            semantic_before=before,
            semantic_after=after,
            frame=capture.metadata,
            scene=scene,
            projection_id=projection,
            signal_targets=targets,
        )
        return ObservedRailRouteUI(observation, capture)

    async def capabilities(self) -> RailRouteUICapabilities:
        try:
            observed = await self.observe()
        except RailRouteUIObservationError as error:
            return RailRouteUICapabilities(actions=(), mutation_allowed=False, reason=str(error))
        observation = observed.observation
        if observation.scene is not RailRouteUIScene.GAMEPLAY:
            return RailRouteUICapabilities(
                actions=("set_route_ui",),
                mutation_allowed=False,
                reason=f"scene is {observation.scene.value}",
            )
        return RailRouteUICapabilities(
            actions=("set_route_ui",),
            mutation_allowed=True,
            reason="canonical Test Yard targets and read-only bridge are synchronized",
        )


def _require_continuity(before: GameSnapshot, after: GameSnapshot) -> None:
    if (
        before.bridge_instance_id != after.bridge_instance_id
        or before.game_session_id != after.game_session_id
        or before.map_identity != after.map_identity
        or before.save_identity != after.save_identity
        or after.bridge_sequence <= before.bridge_sequence
    ):
        raise RailRouteUIObservationError("bridge, session, map, or save identity changed")
    if after.map_identity.value != TEST_YARD_MAP_ID or after.map_identity.label != TEST_YARD_LABEL:
        raise RailRouteUIObservationError("UI mutation is allowed only in the canonical Test Yard")
    if after.game_state.get("game_mode") != "play" or after.game_state.get("paused") is not True:
        raise RailRouteUIObservationError("Test Yard must be loaded in play mode and paused")


def _resolve_test_yard_targets(
    snapshot: GameSnapshot, capture: CapturedDesktopFrame
) -> tuple[SignalScreenTarget, ...]:
    surface = surface_from(snapshot, "signals")
    if surface.coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
        raise RailRouteUIObservationError("signal coverage must be observed_complete")
    semantic: list[tuple[int, int, str, str]] = []
    for entity in surface.entities:
        internal = entity.values.get("internal_name")
        name = entity.values.get("name")
        if not isinstance(internal, str) or not isinstance(name, str):
            raise RailRouteUIObservationError("signal identity fields are unavailable")
        match = _SIGNAL_NAME.fullmatch(internal)
        if match is None:
            raise RailRouteUIObservationError("signal grid identity is not recognized")
        semantic.append((int(match.group("x")), int(match.group("y")), name, internal))
    if {item[2] for item in semantic} != {"SIG-C-W", "SIG-W-IN", "SIG-C-E", "SIG-E-IN"}:
        raise RailRouteUIObservationError("canonical Test Yard must expose exactly four signals")
    peaks = _signal_peaks(capture.image, count=4)
    if len(peaks) != 4:
        raise RailRouteUIObservationError("exactly four visible manual signals were not recognized")
    targets: list[SignalScreenTarget] = []
    for item, peak in zip(sorted(semantic), peaks, strict=True):
        grid_x, grid_y, name, internal = item
        score, x, y = peak
        targets.append(
            SignalScreenTarget(
                signal_id=name,
                internal_name=internal,
                grid_x=grid_x,
                grid_y=grid_y,
                point=ScreenPoint(
                    x=round(x / capture.metadata.display_scale),
                    y=round(y / capture.metadata.display_scale),
                ),
                shape_score=score,
            )
        )
    return tuple(sorted(targets, key=lambda target: target.signal_id))


def _signal_peaks(image: Image.Image, *, count: int) -> list[tuple[int, int, int]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    center_y = round(height * 0.517)
    candidates = [
        (_signal_shape_score(rgb, x, center_y), x, center_y)
        for x in range(round(width * 0.1), round(width * 0.9), max(2, width // 760))
    ]
    selected: list[tuple[int, int, int]] = []
    separation = round(width * 0.04)
    for candidate in sorted(candidates, reverse=True):
        score, x, _ = candidate
        if score < max(120, round(width * height * 0.000055)):
            break
        if all(abs(x - prior_x) > separation for _, prior_x, _ in selected):
            selected.append(candidate)
        if len(selected) == count:
            break
    return sorted(selected, key=lambda value: value[1])


def _signal_shape_score(image: Image.Image, x: int, y: int) -> int:
    width, height = image.size
    dx = max(12, round(width * 0.0093))
    inner = max(7, round(height * 0.006))
    outer = max(18, round(height * 0.0195))
    score = 0
    for current_x in range(max(0, x - dx), min(width, x + dx + 1)):
        rows = range(max(0, y - outer), max(0, y - inner))
        rows_below = range(min(height, y + inner), min(height, y + outer + 1))
        for current_y in (*rows, *rows_below):
            red, green, blue = cast("tuple[int, int, int]", image.getpixel((current_x, current_y)))
            colored_outline = red > 90 and green > 65 and blue < 100
            neutral_outline = (
                red > 100
                and green > 100
                and blue > 100
                and max(red, green, blue) - min(red, green, blue) < 60
            )
            if colored_outline or neutral_outline:
                score += 1
    return score


def _classify_scene(image: Image.Image) -> RailRouteUIScene:
    rgb = image.convert("RGB")
    width, height = rgb.size
    y = min(height - 1, round(height * 0.74))
    yellow = 0
    for x in range(width):
        red, green, blue = cast("tuple[int, int, int]", rgb.getpixel((x, y)))
        if red > 120 and green > 100 and blue < 80:
            yellow += 1
    if yellow > width * 0.1:
        return RailRouteUIScene.CONSTRUCTION_OPEN
    return RailRouteUIScene.GAMEPLAY


def _projection_id(capture: CapturedDesktopFrame, targets: tuple[SignalScreenTarget, ...]) -> str:
    value = "|".join(
        [
            f"{capture.metadata.pixel_width}x{capture.metadata.pixel_height}",
            *(
                f"{target.internal_name}:{round(target.point.x / 8)}:{round(target.point.y / 8)}"
                for target in targets
            ),
        ]
    )
    return hashlib.sha256(value.encode()).hexdigest()
