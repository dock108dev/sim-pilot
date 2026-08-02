"""Two-cycle, UI-driven Rail Route route allocation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sim_pilot.computer_control.models import InputGesture, InputGestureKind
from sim_pilot.game_bridge.models import CoverageStatus, GameSnapshot, ObservedEntity
from sim_pilot.rail_route.bridge.query import surface_from
from sim_pilot.rail_route.models import RailRouteAction, RailRouteIntent
from sim_pilot.rail_route.ui.errors import (
    RailRouteUIObservationError,
    RailRouteUIVerificationError,
)
from sim_pilot.rail_route.ui.models import RailRouteUIObservation, RailRouteUIScene
from sim_pilot.rail_route.ui.observer import (
    TEST_YARD_ROUTE,
    ObservedRailRouteUI,
    RailRouteUIObserver,
)


class RailRouteUIRouteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    intent: RailRouteIntent
    before: RailRouteUIObservation
    after: RailRouteUIObservation
    gestures_sent: int
    dry_run: bool
    verified: bool
    message: str


async def execute_set_route_ui(
    intent: RailRouteIntent,
    *,
    dry_run: bool = False,
    observer_factory: Callable[[], RailRouteUIObserver] = RailRouteUIObserver,
) -> RailRouteUIRouteResult:
    if intent.action is not RailRouteAction.SET_ROUTE:
        raise RailRouteUIObservationError("UI route controller requires set_route intent")
    origin = intent.origin_signal
    destination = intent.destination_signal
    assert origin is not None and destination is not None
    if (origin, destination) != TEST_YARD_ROUTE:
        raise RailRouteUIObservationError(
            "initial UI capability is restricted to SIG-W-IN -> SIG-C-W in the Test Yard"
        )
    observer = observer_factory()
    before = await observer.observe()
    _preflight(before, origin, destination)
    if dry_run:
        return RailRouteUIRouteResult(
            intent=intent,
            before=before.observation,
            after=before.observation,
            gestures_sent=0,
            dry_run=True,
            verified=True,
            message=f"Dry run: would click {origin}, verify preview, then click {destination}.",
        )

    origin_target = _target(before, origin)
    first_gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=origin_target.point,
        expected_process_id=before.observation.frame.process_id,
        expected_window_id=before.observation.frame.window_id,
        expected_window_bounds=before.observation.frame.window_bounds,
        expected_frame_id=before.observation.frame.frame_id,
        expected_scene=before.observation.scene.value,
        target_id=origin_target.signal_id,
        intended_effect="select the origin signal for route preview",
    )
    observer.backend.execute(first_gesture, frame=before.observation.frame)

    try:
        preview = await observer.observe()
    except Exception as error:
        raise RailRouteUIVerificationError(
            "origin click was sent but a fresh preview observation failed; no retry attempted"
        ) from error
    _verify_preview(before, preview, origin, destination)

    destination_target = _target(preview, destination)
    second_gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=destination_target.point,
        expected_process_id=preview.observation.frame.process_id,
        expected_window_id=preview.observation.frame.window_id,
        expected_window_bounds=preview.observation.frame.window_bounds,
        expected_frame_id=preview.observation.frame.frame_id,
        expected_scene=preview.observation.scene.value,
        target_id=destination_target.signal_id,
        intended_effect="complete the route at the destination signal",
    )
    observer.backend.execute(second_gesture, frame=preview.observation.frame)

    try:
        after = await observer.observe()
    except Exception as error:
        raise RailRouteUIVerificationError(
            "destination click was sent but final observation failed; no retry attempted"
        ) from error
    _verify_route(before.observation.semantic_after, after.observation.semantic_after, origin)
    return RailRouteUIRouteResult(
        intent=intent,
        before=before.observation,
        after=after.observation,
        gestures_sent=2,
        dry_run=False,
        verified=True,
        message=f"Route {origin} -> {destination} set through the game UI; allocation verified.",
    )


def _preflight(observed: ObservedRailRouteUI, origin: str, destination: str) -> None:
    observation = observed.observation
    if observation.scene is not RailRouteUIScene.GAMEPLAY:
        raise RailRouteUIObservationError(
            f"cannot set a route from scene {observation.scene.value}; "
            "close Construction and overlays"
        )
    _target(observed, origin)
    _target(observed, destination)
    snapshot = observation.semantic_after
    signals = surface_from(snapshot, "signals")
    routes = surface_from(snapshot, "routes")
    occupancy = surface_from(snapshot, "track_occupancy")
    for surface in (signals, routes, occupancy):
        if surface.coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
            raise RailRouteUIObservationError(
                f"{surface.coverage.surface} must be observed_complete"
            )
    origin_entity = _signal(signals.entities, origin)
    _signal(signals.entities, destination)
    if origin_entity.values.get("current_route_to") is not None:
        raise RailRouteUIObservationError("origin already has an active route")
    if origin_entity.values.get("locked") is not False:
        raise RailRouteUIObservationError("origin signal is locked")
    if origin_entity.values.get("allocation_state") != "Free":
        raise RailRouteUIObservationError("origin signal is not free")
    if occupancy.entities:
        raise RailRouteUIObservationError("Test Yard path is occupied or allocated")
    if routes.entities:
        raise RailRouteUIObservationError("Test Yard already contains an active route")


def _verify_preview(
    before: ObservedRailRouteUI,
    preview: ObservedRailRouteUI,
    origin: str,
    destination: str,
) -> None:
    if preview.observation.scene is not RailRouteUIScene.GAMEPLAY:
        raise RailRouteUIVerificationError(
            "origin click left the verified gameplay scene; no retry attempted"
        )
    if preview.observation.projection_id != before.observation.projection_id:
        raise RailRouteUIVerificationError(
            "projection changed after origin click; no destination click was sent"
        )
    if preview.observation.frame.sha256 == before.observation.frame.sha256:
        raise RailRouteUIVerificationError(
            "origin click produced no visible route-preview change; no retry attempted"
        )
    _target(preview, origin)
    _target(preview, destination)
    _require_identity_continuity(
        before.observation.semantic_after, preview.observation.semantic_after
    )


def _verify_route(before: GameSnapshot, after: GameSnapshot, origin: str) -> None:
    _require_identity_continuity(before, after)
    before_routes = surface_from(before, "routes")
    after_routes = surface_from(after, "routes")
    before_ids = {entity.entity_id for entity in before_routes.entities}
    after_ids = {entity.entity_id for entity in after_routes.entities}
    if after_ids - {origin} != before_ids:
        raise RailRouteUIVerificationError(
            "destination click changed unrelated active routes; no retry attempted"
        )
    matches = [entity for entity in after_routes.entities if entity.entity_id == origin]
    signals = surface_from(after, "signals")
    origin_entity = _signal(signals.entities, origin)
    if len(matches) != 1 or origin_entity.values.get("current_route_to") is None:
        raise RailRouteUIVerificationError(
            "destination click was sent but the expected route was not observed; no retry attempted"
        )


def _require_identity_continuity(before: GameSnapshot, after: GameSnapshot) -> None:
    if (
        before.bridge_instance_id != after.bridge_instance_id
        or before.game_session_id != after.game_session_id
        or before.map_identity != after.map_identity
        or before.save_identity != after.save_identity
        or after.bridge_sequence <= before.bridge_sequence
    ):
        raise RailRouteUIVerificationError(
            "bridge, session, map, or save identity changed after input; no retry attempted"
        )


def _target(observed: ObservedRailRouteUI, name: str):
    matches = [target for target in observed.observation.signal_targets if target.signal_id == name]
    if len(matches) != 1:
        raise RailRouteUIObservationError(f"signal {name!r} did not resolve to one screen target")
    return matches[0]


def _signal(entities: tuple[ObservedEntity, ...], name: str) -> ObservedEntity:
    matches = [entity for entity in entities if entity.entity_id == name]
    if len(matches) != 1:
        raise RailRouteUIObservationError(f"signal {name!r} did not resolve exactly once")
    return matches[0]
