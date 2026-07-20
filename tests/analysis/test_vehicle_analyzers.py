from sim_pilot.analysis.analyzers.vehicles import FleetSummaryAnalyzer, VehiclePerformanceAnalyzer
from sim_pilot.analysis.contracts import (
    AnalysisFilter,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisRequest,
    AnalysisStatus,
    AnalysisSubjectType,
    AnalysisType,
    RankingDirection,
    RankingMetric,
    RankingRequest,
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


def test_vehicle_analyzer_reports_filtered_no_match_as_clean_result() -> None:
    result = VehiclePerformanceAnalyzer().analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
            question="Are any vehicles idle?",
            filters=(
                AnalysisFilter(
                    field=AnalysisFilterField.RUNNING_STATE,
                    operator=AnalysisFilterOperator.EQUAL,
                    values=("idle",),
                ),
            ),
        ),
        snapshot(vehicles=(vehicle("running"),)),
        None,
    )
    assert result.status is AnalysisStatus.COMPLETED
    assert result.findings == ()
    assert result.answer == "No observed vehicles matched the requested filters."


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


def test_vehicle_positive_ranking_evaluates_the_full_eligible_population() -> None:
    result = VehiclePerformanceAnalyzer().analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
            question="Which vehicle performed best last year?",
            ranking=RankingRequest(
                metric=RankingMetric.PROFIT_LAST_YEAR,
                direction=RankingDirection.DESCENDING,
            ),
        ),
        snapshot(
            vehicles=(
                vehicle("best", previous=500),
                vehicle("middle", previous=100),
                vehicle("loss", previous=-10),
            )
        ),
        None,
    )

    assert result.findings[0].evidence[0].entity_id == "best"
    assert result.population is not None
    assert result.population.evaluated_count == 3
    assert result.population.excluded_count == 0


def test_fleet_summary_ranks_vehicle_types_by_aggregate_profit() -> None:
    result = FleetSummaryAnalyzer().analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.FLEET_SUMMARY,
            question="Which vehicle type is dragging down profitability?",
            subject_type=AnalysisSubjectType.VEHICLE,
            ranking=RankingRequest(
                metric=RankingMetric.VEHICLE_TYPE_AGGREGATE_PROFIT,
                direction=RankingDirection.ASCENDING,
            ),
        ),
        snapshot(
            vehicles=(
                vehicle("rail-loss", kind="rail", previous=-200),
                vehicle("rail-gain", kind="rail", previous=50),
                vehicle("road-gain", kind="road", previous=100),
            )
        ),
        None,
    )

    assert result.findings[0].metric_value == -150
    assert "1 of 2 lost money" in result.findings[0].summary
    assert result.population is not None
    assert result.population.evaluated_count == 2
