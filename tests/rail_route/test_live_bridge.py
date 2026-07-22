from __future__ import annotations

import asyncio
import os

import pytest

from sim_pilot.game_bridge import CoverageStatus, IdentityStatus
from sim_pilot.rail_route.bridge import rail_route_bridge_client

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("SIM_PILOT_LIVE_RAIL_ROUTE_BRIDGE") != "1",
    reason="requires the explicit disposable Rail Route bridge live-test gate",
)
def test_live_read_only_bridge_handshake_snapshot_and_reconnect() -> None:
    asyncio.run(_exercise_live_bridge())


async def _exercise_live_bridge() -> None:
    client = rail_route_bridge_client()
    try:
        capabilities = await client.connect()
        first = await client.request_full_snapshot()
        bridge_id = first.bridge_instance_id
        session_id = first.game_session_id
        assert capabilities.gameplay_actions == ()
        assert first.game_id == "rail-route"
        assert first.game_version == "2.3.24"
        game_state = next(
            surface for surface in first.surfaces if surface.coverage.surface == "game_state"
        )
        assert game_state.coverage.status is CoverageStatus.OBSERVED_COMPLETE
        assert game_state.coverage.fields == (
            "current_time",
            "game_mode",
            "paused",
            "simulation_speed",
        )
        assert first.game_state["current_time"] is not None
        assert isinstance(first.game_state["paused"], bool)
        assert first.map_identity.status is IdentityStatus.OBSERVED
        semantic = {
            surface.coverage.surface: surface
            for surface in first.surfaces
            if surface.coverage.surface != "game_state"
        }
        assert set(semantic) == {
            "incoming_traffic",
            "platforms",
            "routes",
            "signals",
            "stations",
            "switches",
            "track_occupancy",
            "trains",
        }
        assert all(
            surface.coverage.status is CoverageStatus.OBSERVED_COMPLETE
            for surface in semantic.values()
        )
        assert semantic["stations"].entities
        assert semantic["platforms"].entities
        assert semantic["signals"].entities
        assert semantic["incoming_traffic"].entities
        assert semantic["track_occupancy"].entities
        assert semantic["trains"].entities
        incoming_numbers = {
            reporting_number
            for entity in semantic["incoming_traffic"].entities
            if isinstance(reporting_number := entity.values.get("reporting_number"), str)
        }
        assert {"Com1011", "Com1012"} <= incoming_numbers
        incoming_by_number = {
            reporting_number: entity
            for entity in semantic["incoming_traffic"].entities
            if isinstance(reporting_number := entity.values.get("reporting_number"), str)
        }
        assert incoming_by_number["Com1011"].values["due_time"] == "09:01:00"
        assert incoming_by_number["Com1012"].values["due_time"] == "10:01:00"
        assert incoming_by_number["Com1011"].values["requested_platform"] == 2
        assert incoming_by_number["Com1012"].values["requested_platform"] == 2
        segment_kinds = {
            segment_kind
            for entity in semantic["track_occupancy"].entities
            if isinstance(segment_kind := entity.values.get("segment_kind"), str)
        }
        assert "occupied" in segment_kinds
        allocation_states = {
            allocation_state
            for entity in semantic["track_occupancy"].entities
            if isinstance(allocation_state := entity.values.get("allocation_state"), str)
        }
        assert {"Allocated", "Occupied"} <= allocation_states
    finally:
        await client.close()

    reconnect = rail_route_bridge_client()
    try:
        await reconnect.connect()
        second = await reconnect.request_full_snapshot()
        assert second.bridge_instance_id == bridge_id
        assert second.game_session_id == session_id
        assert second.map_identity == first.map_identity
        assert second.save_identity == first.save_identity
        assert second.surfaces == tuple(
            sorted(second.surfaces, key=lambda item: item.coverage.surface)
        )
        first_ids = {
            surface.coverage.surface: tuple(entity.entity_id for entity in surface.entities)
            for surface in first.surfaces
        }
        second_ids = {
            surface.coverage.surface: tuple(entity.entity_id for entity in surface.entities)
            for surface in second.surfaces
        }
        assert second_ids == first_ids
    finally:
        await reconnect.close()
