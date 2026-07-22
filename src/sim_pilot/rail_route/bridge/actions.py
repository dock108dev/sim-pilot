"""One-shot, fail-closed Rail Route set_route orchestration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.game_bridge import (
    GameBridgeError,
    GameSnapshot,
    ObservedEntity,
    SetRouteResponsePayload,
)
from sim_pilot.rail_route.models import RailRouteAction, RailRouteIntent

from .client import rail_route_bridge_client
from .errors import RailRouteBridgeActionError, RailRouteBridgeVerificationError
from .query import surface_from


class RailRouteSetRouteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    intent: RailRouteIntent
    before: GameSnapshot
    action: SetRouteResponsePayload
    after: GameSnapshot
    verified: bool
    message: str = Field(min_length=1)


async def execute_set_route(intent: RailRouteIntent) -> RailRouteSetRouteResult:
    if intent.action is not RailRouteAction.SET_ROUTE:
        raise RailRouteBridgeActionError("semantic route executor requires set_route")
    assert intent.origin_signal is not None
    assert intent.destination_signal is not None

    client = rail_route_bridge_client()
    action_requested = False
    try:
        capabilities = await client.connect()
        if capabilities.gameplay_actions != ("set_route",):
            raise RailRouteBridgeActionError("bridge must advertise only set_route")
        before = await client.request_full_snapshot()
        _preflight_snapshot(before, intent.origin_signal, intent.destination_signal)
        action_requested = True
        action, after = await client.request_set_route(
            origin_signal=intent.origin_signal,
            destination_signal=intent.destination_signal,
            before=before,
        )
        if action.outcome != "succeeded":
            error_type = (
                RailRouteBridgeVerificationError if action.executed else RailRouteBridgeActionError
            )
            raise error_type(
                f"set_route rejected[{action.reason_code}]: {action.detail}; no retry attempted"
            )
        _verify_postcondition(before, after, action)
        return RailRouteSetRouteResult(
            intent=intent,
            before=before,
            action=action,
            after=after,
            verified=True,
            message=(
                f"Route {intent.origin_signal} -> {intent.destination_signal} set once; "
                "allocation verified from a fresh semantic snapshot."
            ),
        )
    except GameBridgeError as error:
        if action_requested:
            raise RailRouteBridgeVerificationError(
                "set_route may have been submitted but bridge continuity or fresh verification "
                "failed; no retry attempted"
            ) from error
        raise RailRouteBridgeActionError(f"set_route bridge preflight failed: {error}") from error
    finally:
        await client.close()


def _preflight_snapshot(snapshot: GameSnapshot, origin: str, destination: str) -> None:
    if snapshot.game_state.get("game_mode") != "play":
        raise RailRouteBridgeActionError("set_route requires a loaded game in play mode")
    if snapshot.game_state.get("paused") is not True:
        raise RailRouteBridgeActionError(
            "set_route live proof requires the disposable session to be paused"
        )
    signals = surface_from(snapshot, "signals")
    routes = surface_from(snapshot, "routes")
    surface_from(snapshot, "track_occupancy")
    origin_entity = _exact_signal(signals.entities, origin, "origin")
    _exact_signal(signals.entities, destination, "destination")
    if origin_entity.values.get("current_route_to") is not None:
        raise RailRouteBridgeActionError("origin already has an active route")
    if origin_entity.values.get("locked") is not False:
        raise RailRouteBridgeActionError("origin signal is locked or its lock state is unavailable")
    if origin_entity.values.get("allocation_state") != "Free":
        raise RailRouteBridgeActionError("origin signal is not free")
    if origin_entity.values.get("occupied_train_ids") != []:
        raise RailRouteBridgeActionError("origin signal is occupied or occupancy is unavailable")
    if any(entity.entity_id == origin for entity in routes.entities):
        raise RailRouteBridgeActionError("origin already appears in active routes")


def _verify_postcondition(
    before: GameSnapshot, after: GameSnapshot, action: SetRouteResponsePayload
) -> None:
    before_routes = surface_from(before, "routes")
    after_routes = surface_from(after, "routes")
    expected_existing = {
        (entity.entity_id, entity.values.get("destination_connection"))
        for entity in before_routes.entities
    }
    actual_existing = {
        (entity.entity_id, entity.values.get("destination_connection"))
        for entity in after_routes.entities
        if entity.entity_id != action.origin_signal
    }
    if actual_existing != expected_existing:
        raise RailRouteBridgeVerificationError(
            "one route request executed but unrelated active routes changed; no retry attempted"
        )
    matches = [
        entity
        for entity in after_routes.entities
        if entity.entity_id == action.origin_signal
        and entity.values.get("destination_connection") == action.destination_connection
    ]
    signals = surface_from(after, "signals")
    origin = _exact_signal(signals.entities, action.origin_signal, "origin")
    if len(matches) != 1 or origin.values.get("current_route_to") != action.destination_connection:
        raise RailRouteBridgeVerificationError(
            "one route request executed but the expected route allocation was not observed; "
            "no retry attempted"
        )


def _exact_signal(entities: tuple[ObservedEntity, ...], name: str, role: str) -> ObservedEntity:
    matches = [
        entity
        for entity in entities
        if entity.entity_id == name and entity.values.get("name") == name
    ]
    if len(matches) != 1:
        raise RailRouteBridgeActionError(
            f"{role} signal {name!r} must resolve exactly once in the fresh snapshot"
        )
    return matches[0]
