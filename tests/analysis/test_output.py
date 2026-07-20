from sim_pilot.analysis.contracts import (
    AnalysisRequest,
    AnalysisType,
    RankingDirection,
    RankingMetric,
    RankingRequest,
)
from sim_pilot.analysis.output import render_analysis
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from tests.analysis.helpers import snapshot


def test_compact_answer_leads_with_answer_and_has_one_result_and_limitation() -> None:
    world = snapshot()
    response = AnalysisService(default_analyzer_registry()).analyze(
        AnalysisRequest(analysis_type=AnalysisType.FINANCIAL_SUMMARY, question="Finances?"),
        world,
    )
    rendered = render_analysis(response, snapshot=world)
    assert rendered.splitlines()[0] == response.answer
    assert rendered.count("\nEvidence\n") == 1
    assert "\nLimitation\n" in rendered
    assert "\nRecommendation\n" not in rendered


def test_detailed_ranked_answer_shows_evidence_counts_and_snapshot_identity() -> None:
    world = snapshot()
    response = AnalysisService(default_analyzer_registry()).analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
            question="Which vehicles are worst?",
            ranking=RankingRequest(
                metric=RankingMetric.PROFIT_LAST_YEAR,
                direction=RankingDirection.ASCENDING,
            ),
        ),
        world,
    )
    rendered = render_analysis(response, detailed=True, snapshot=world)
    assert "Evaluated: 0; excluded for missing metric: 0" in rendered
    assert "Tie-break: canonical entity ID, ascending." in rendered
    assert f"ID: {world.metadata.snapshot_id}" in rendered
    assert f"World: {world.metadata.world_id}" in rendered


def test_no_result_answer_does_not_manufacture_a_problem() -> None:
    world = snapshot()
    response = AnalysisService(default_analyzer_registry()).analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
            question="Any vehicle problems?",
        ),
        world,
    )
    rendered = render_analysis(response, snapshot=world)
    assert rendered.startswith("Insufficient data:")
    assert "did not contain enough supported evidence" in rendered
