from sim_pilot.analysis.analyzers.network import (
    RoutePerformanceAnalyzer,
    StationPerformanceAnalyzer,
)
from sim_pilot.analysis.contracts import (
    AnalysisRequest,
    AnalysisType,
    FindingSeverity,
    RankingDirection,
    RankingMetric,
    RankingRequest,
)
from sim_pilot.domain.world import CargoFlow, CargoFlowScope, Coordinates, Route, Station, Vehicle
from tests.analysis.helpers import snapshot


def vehicle(identifier: str, profit: int, route_id: str) -> Vehicle:
    return Vehicle(
        id=identifier,
        type="rail",
        name=identifier,
        age_days=10,
        profit_this_year=profit,
        profit_last_year=profit,
        running_state="running",
        coordinates=None,
        route_id=route_id,
        in_depot=False,
        owner_id="company-1",
    )


def test_station_waiting_threshold_and_wording() -> None:
    station = Station(
        id="station-1",
        name="Transfer",
        owner_id="company-1",
        coordinates=Coordinates(x=1, y=1),
        waiting_cargo=(
            CargoFlow(
                cargo_id="cargo-1",
                cargo_type="Goods",
                scope=CargoFlowScope.STATION,
                entity_id="station-1",
                waiting=1_000,
            ),
        ),
        vehicle_count=0,
    )
    world = snapshot().model_copy(update={"stations": (station,)})

    result = StationPerformanceAnalyzer().analyze(
        AnalysisRequest(analysis_type=AnalysisType.STATION_PERFORMANCE, question="Waiting?"),
        world,
        None,
    )

    underserved = next(
        item for item in result.findings if item.finding_code == "potentially_underserved_station"
    )
    assert underserved.severity is FindingSeverity.WARNING
    assert "congest" not in underserved.summary.lower()
    assert underserved.evidence


def test_route_profit_and_share_are_derived_from_members() -> None:
    route = Route(
        id="route-1",
        owner_id="company-1",
        vehicle_ids=("vehicle-1", "vehicle-2"),
        ordered_station_ids=("station-1", "station-2"),
        inferred_route_type="rail",
    )
    world = snapshot(
        vehicles=(vehicle("vehicle-1", -100, route.id), vehicle("vehicle-2", -50, route.id))
    ).model_copy(update={"routes": (route,)})

    result = RoutePerformanceAnalyzer().analyze(
        AnalysisRequest(analysis_type=AnalysisType.ROUTE_PERFORMANCE, question="Weak routes?"),
        world,
        None,
    )

    values = {item.finding_code: item.metric_value for item in result.findings}
    assert values["negative_route_profit"] == -150
    assert values["negative_route_vehicle_share"] == 1.0
    assert any("identity is inferred" in item for item in result.limitations)


def test_route_ranking_counts_losing_vehicles_without_substituting_fleet_size() -> None:
    route = Route(
        id="route-1",
        owner_id="company-1",
        vehicle_ids=("vehicle-1", "vehicle-2"),
        ordered_station_ids=("station-1", "station-2"),
        inferred_route_type="rail",
    )
    world = snapshot(
        vehicles=(vehicle("vehicle-1", -100, route.id), vehicle("vehicle-2", 50, route.id))
    ).model_copy(update={"routes": (route,)})

    result = RoutePerformanceAnalyzer().analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.ROUTE_PERFORMANCE,
            question="Which routes have the most losing vehicles?",
            ranking=RankingRequest(
                metric=RankingMetric.ROUTE_NEGATIVE_VEHICLE_COUNT,
                direction=RankingDirection.DESCENDING,
            ),
        ),
        world,
        None,
    )

    assert result.findings[0].metric_name == "route_negative_vehicle_count"
    assert result.findings[0].metric_value == 1
    assert result.population is not None
    assert result.population.evaluated_count == 1
