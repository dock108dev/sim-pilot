from sim_pilot.analysis.analyzers.coverage import (
    IndustryOpportunitiesAnalyzer,
    ServiceCoverageAnalyzer,
    TownCoverageAnalyzer,
)
from sim_pilot.analysis.contracts import AnalysisRequest, AnalysisType
from sim_pilot.domain.world import (
    CargoFlow,
    CargoFlowScope,
    Coordinates,
    Industry,
    Station,
    Town,
    WorldSnapshot,
)
from tests.analysis.helpers import snapshot


def coverage_world() -> WorldSnapshot:
    station = Station(
        id="station-1",
        name="Network Edge",
        owner_id="company-1",
        coordinates=Coordinates(x=10, y=10),
    )
    towns = (
        Town(id="small", name="Small", population=1_000, coordinates=Coordinates(x=20, y=10)),
        Town(id="large", name="Large", population=5_000, coordinates=Coordinates(x=20, y=10)),
        Town(
            id="served",
            name="Served",
            population=9_000,
            coordinates=Coordinates(x=10, y=10),
            station_count=1,
        ),
    )
    industries = (
        Industry(
            id="industry-1",
            type="mine",
            name="Mine",
            coordinates=Coordinates(x=15, y=10),
            production=(
                CargoFlow(
                    cargo_id="coal",
                    cargo_type="Coal",
                    scope=CargoFlowScope.INDUSTRY,
                    entity_id="industry-1",
                    produced=1_000,
                ),
            ),
        ),
    )
    return snapshot().model_copy(
        update={"stations": (station,), "towns": towns, "industries": industries}
    )


def test_town_opportunity_score_and_tie_breaking_are_deterministic() -> None:
    result = TownCoverageAnalyzer().analyze(
        AnalysisRequest(analysis_type=AnalysisType.TOWN_COVERAGE, question="Unserved towns?"),
        coverage_world(),
        None,
    )
    assert [item.evidence[0].entity_id for item in result.findings] == ["large", "small"]
    inputs = result.findings[0].evidence[0].metric_inputs
    assert inputs["population_points"] == 60.0
    assert inputs["proximity_points"] == 24.0


def test_industry_and_combined_coverage_use_exposed_scores() -> None:
    world = coverage_world()
    industry = IndustryOpportunitiesAnalyzer().analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.INDUSTRY_OPPORTUNITIES,
            question="Industries?",
        ),
        world,
        None,
    )
    combined = ServiceCoverageAnalyzer().analyze(
        AnalysisRequest(analysis_type=AnalysisType.SERVICE_COVERAGE, question="Coverage?"),
        world,
        None,
    )
    assert industry.findings[0].metric_value == 97.0
    assert len(combined.findings) == 3
    assert all(item.analysis_type is AnalysisType.SERVICE_COVERAGE for item in combined.findings)
