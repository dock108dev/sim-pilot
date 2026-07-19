import asyncio
import json

from sim_pilot.adapters.openttd import OpenTTDAdapter
from sim_pilot.domain.world import (
    Coordinates,
    CoverageStatus,
    Station,
    Vehicle,
    VehicleOrder,
    VehicleOrderKind,
)
from sim_pilot.openttd.gamescript.client import GameScriptBridgeClient
from sim_pilot.openttd.models import OpenTTDObservationState
from sim_pilot.openttd.route_inference import infer_routes
from tests.openttd.gamescript.helpers import FakeBridgeTransport, world_sync_messages
from tests.openttd.helpers import FakeOpenTTDClient


def test_adapter_translates_complete_world_without_raw_ids() -> None:
    async def scenario() -> OpenTTDObservationState:
        bridge = GameScriptBridgeClient(FakeBridgeTransport(world_sync_messages()), company_id=0)
        adapter = OpenTTDAdapter(FakeOpenTTDClient(), bridge=bridge)
        await adapter.initialize()
        try:
            observation = await adapter.observe()
            return OpenTTDObservationState.model_validate_json(json.dumps(observation.state))
        finally:
            await adapter.shutdown()

    state = asyncio.run(scenario())
    world = state.world
    assert world is not None
    assert state.adapter.integration_version == "admin-network-v3+gamescript-v2"
    assert state.adapter.capabilities.supports_world_snapshots is True
    assert world.towns[0].id.startswith("town:")
    assert world.towns[0].id != "1"
    assert world.companies[0].is_ai is False
    assert world.metadata.observer_company_id == world.companies[0].id
    assert world.vehicles[0].route_id is not None
    assert world.routes[0].ordered_station_ids == (world.stations[0].id,)
    coverage = {item.category: item.status for item in world.coverage}
    assert coverage["infrastructure"] is CoverageStatus.UNAVAILABLE
    assert coverage["terrain"] is CoverageStatus.UNAVAILABLE


def test_route_identity_is_stable_when_order_cycles_rotate() -> None:
    stations = tuple(
        Station(
            id=f"station:{index}",
            name=f"Station {index}",
            owner_id="company:1",
            coordinates=Coordinates(x=index, y=index),
        )
        for index in (1, 2)
    )
    orders = tuple(
        VehicleOrder(
            index=index,
            kind=VehicleOrderKind.STATION,
            destination_id=station.id,
            destination_coordinates=station.coordinates,
        )
        for index, station in enumerate(stations)
    )

    def vehicle(identifier: str, vehicle_orders: tuple[VehicleOrder, ...]) -> Vehicle:
        return Vehicle(
            id=identifier,
            type="rail",
            name="Train",
            age_days=1,
            profit_this_year=0,
            profit_last_year=0,
            running_state="running",
            coordinates=Coordinates(x=0, y=0),
            orders=vehicle_orders,
            in_depot=False,
            owner_id="company:1",
        )

    first = vehicle("vehicle:1", orders)
    second = vehicle("vehicle:2", orders[1:] + orders[:1])
    _, routes = infer_routes((first, second), stations)
    assert len(routes) == 1
    assert routes[0].vehicle_ids == ("vehicle:1", "vehicle:2")
