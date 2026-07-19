from sim_pilot.analysis.analyzers.vehicles import FleetSummaryAnalyzer, VehiclePerformanceAnalyzer
from sim_pilot.analysis.contracts import (
    AnalysisFilter,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisRequest,
    AnalysisStatus,
    AnalysisType,
)
from sim_pilot.domain.world import Vehicle
from tests.analysis.helpers import snapshot


def vehicle(
    identifier: str,
    *,
    kind: str = "road",
    current: int = 10,
    previous: int = 10,
    age: int = 1,
    state: str = "running",
    depot: bool = False,
    route_id: str | None = "route-1",
) -> Vehicle:
    return Vehicle(
        id=identifier,
        type=kind,
        name=identifier,
        age_days=age,
        profit_this_year=current,
        profit_last_year=previous,
        running_state=state,
        coordinates=None,
        route_id=route_id,
        in_depot=depot,
        owner_id="company-1",
    )


def test_vehicle_analyzer_filters_and_applies_boundaries() -> None:
    world = snapshot(
        vehicles=(
            vehicle("old-loss", kind="rail", previous=-1, age=7_305, state="stopped"),
            vehicle("road", kind="road", previous=-100),
        )
    )
    request = AnalysisRequest(
        analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
        question="Which trains need review?",
        filters=(
            AnalysisFilter(
                field=AnalysisFilterField.VEHICLE_TYPE,
                operator=AnalysisFilterOperator.EQUAL,
                values=("rail",),
            ),
        ),
    )

    result = VehiclePerformanceAnalyzer().analyze(request, world, None)

    assert {item.finding_code for item in result.findings} == {
        "negative_last_year_profit",
        "old_vehicle",
        "idle_vehicle",
    }
    assert all(item.evidence[0].entity_id == "old-loss" for item in result.findings)


def test_vehicle_analyzer_handles_empty_selection() -> None:
    result = VehiclePerformanceAnalyzer().analyze(
        AnalysisRequest(analysis_type=AnalysisType.VEHICLE_PERFORMANCE, question="Vehicles"),
        snapshot(),
        None,
    )
    assert result.status is AnalysisStatus.INSUFFICIENT_DATA


def test_fleet_summary_is_deterministic() -> None:
    result = FleetSummaryAnalyzer().analyze(
        AnalysisRequest(analysis_type=AnalysisType.FLEET_SUMMARY, question="Fleet"),
        snapshot(vehicles=(vehicle("2", kind="rail"), vehicle("1", kind="road"))),
        None,
    )
    assert [item.finding_code for item in result.findings] == [
        "fleet_count_rail",
        "fleet_count_road",
    ]
