from sim_pilot.analysis.contracts import AnalysisSubjectType
from sim_pilot.analysis.evidence_view import (
    entity_aliases,
    entity_display_labels,
    render_entity,
    render_finding_evidence,
)
from sim_pilot.analysis.session import AnalysisSessionRecord
from sim_pilot.domain.world import Coordinates, Route, Station, Vehicle
from tests.analysis.helpers import snapshot
from tests.analysis.test_session import response


def test_evidence_view_explains_observed_value_without_raw_json() -> None:
    world = snapshot()
    record = AnalysisSessionRecord(
        analysis_id="analysis:0123456789abcdefabcd",
        response=response(world),
        snapshot=world,
    )
    rendered = render_finding_evidence(record, "finding-cash")
    assert "Kind: observed_fact" in rendered
    assert "observed: 100" in rendered
    assert "C-001 (company)" in rendered


def test_entity_aliases_and_route_drill_down_are_deterministic() -> None:
    vehicle = Vehicle(
        id="vehicle-1",
        type="rail",
        name="Express",
        age_days=10,
        profit_this_year=200,
        profit_last_year=100,
        running_state="running",
        coordinates=Coordinates(x=1, y=2),
        route_id="route-1",
        in_depot=False,
        owner_id="company-1",
    )
    route = Route(
        id="route-1",
        owner_id="company-1",
        vehicle_ids=(vehicle.id,),
        ordered_station_ids=(),
        inferred_route_type="rail",
    )
    world = snapshot(vehicles=(vehicle,)).model_copy(update={"routes": (route,)})
    assert entity_aliases(world, AnalysisSubjectType.VEHICLE) == {"vehicle-1": "V-001"}
    rendered = render_entity(world, AnalysisSubjectType.ROUTE, "R-001")
    assert "Route R-001" in rendered
    assert "Vehicles: 1" in rendered
    assert "identity is inferred" in rendered


def test_route_display_label_uses_ordered_station_names() -> None:
    stations = (
        Station(
            id="station-a",
            name="Buntborough",
            owner_id="company-1",
            coordinates=Coordinates(x=1, y=1),
        ),
        Station(
            id="station-b",
            name="Trunton Woods",
            owner_id="company-1",
            coordinates=Coordinates(x=2, y=2),
        ),
    )
    route = Route(
        id="route-opaque-hash",
        owner_id="company-1",
        vehicle_ids=(),
        ordered_station_ids=("station-a", "station-b"),
        inferred_route_type="rail",
    )
    world = snapshot().model_copy(update={"stations": stations, "routes": (route,)})

    labels = entity_display_labels(world, AnalysisSubjectType.ROUTE)

    assert labels[route.id] == "Route R-001 — Buntborough → Trunton Woods"
    assert "route-opaque-hash" not in labels[route.id]
