import asyncio

import pytest

from sim_pilot.analysis.compiler import (
    AnalysisCompilerContext,
    AnalysisEntityContext,
    DeterministicAnalysisCompiler,
)
from sim_pilot.analysis.contracts import (
    AnalysisStatus,
    AnalysisSubjectType,
    AnalysisType,
    AnswerConcept,
    AnswerMetric,
    AnswerPeriod,
    RankingDirection,
    RankingMetric,
)
from sim_pilot.analysis.output import render_analysis
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.domain.world import Company, FieldChanged, Vehicle
from tests.analysis.helpers import snapshot


def _compile(question: str, *, comparison: str | None = None):
    return asyncio.run(
        DeterministicAnalysisCompiler().compile(
            question,
            context=AnalysisCompilerContext(comparison_snapshot_id=comparison),
        )
    )


def _company_world(*, loan: int = 0):
    return snapshot(
        company=Company(
            id="company-1",
            name="Founder Test",
            cash=2_000_000,
            loan=loan,
            company_value=4_000_000,
            income=1_000_000,
            expenses=-250_000,
        )
    )


@pytest.mark.parametrize(
    ("question", "concept", "metric", "prefix"),
    (
        (
            "How healthy is my company right now?",
            AnswerConcept.HEALTH,
            AnswerMetric.NET_OPERATING_RESULT,
            "The observed company-level operating result is positive",
        ),
        (
            "Why am I losing money?",
            AnswerConcept.LOSS,
            AnswerMetric.NET_OPERATING_RESULT,
            "You are not losing money at company level",
        ),
        (
            "Am I carrying too much debt?",
            AnswerConcept.DEBT,
            AnswerMetric.LOAN,
            "There is no observed outstanding company loan.",
        ),
        (
            "How much cash do I actually have available?",
            AnswerConcept.AVAILABLE_CASH,
            AnswerMetric.CASH,
            "The observed company cash balance available in this snapshot is £2,000,000.",
        ),
    ),
)
def test_company_questions_preserve_intent_and_answer_first(
    question: str,
    concept: AnswerConcept,
    metric: AnswerMetric,
    prefix: str,
) -> None:
    compilation = _compile(question)
    assert compilation.request is not None
    assert compilation.request.answer_intent is not None
    assert compilation.request.answer_intent.concept is concept
    assert compilation.request.answer_intent.requested_metric is metric

    response = AnalysisService(default_analyzer_registry()).analyze(
        compilation.request, _company_world()
    )
    rendered = render_analysis(response, snapshot=_company_world())

    assert rendered.startswith(prefix)
    assert rendered.splitlines()[0] == response.answer
    assert response.presentation is not None
    assert len(rendered.split()) < 80


def test_available_cash_answer_discloses_what_the_balance_excludes() -> None:
    compilation = _compile("How much cash do I actually have available?")
    assert compilation.request is not None
    response = AnalysisService(default_analyzer_registry()).analyze(
        compilation.request, _company_world()
    )
    assert response.presentation is not None
    assert response.presentation.limitation == (
        "The snapshot does not expose committed future costs or infrastructure liabilities."
    )


def test_change_question_without_typed_delta_evidence_is_insufficient() -> None:
    previous = _company_world().model_copy(
        update={
            "metadata": _company_world().metadata.model_copy(
                update={"snapshot_id": "snapshot-previous", "game_date": 10}
            )
        }
    )
    current = _company_world()
    compilation = _compile(
        "Is the company improving or getting worse?",
        comparison=previous.metadata.snapshot_id,
    )
    assert compilation.request is not None

    response = AnalysisService(default_analyzer_registry()).analyze(
        compilation.request, current, previous
    )

    assert response.status is AnalysisStatus.INSUFFICIENT_DATA
    assert response.answer.startswith("I cannot answer the comparison")
    assert "no evaluated typed change evidence" in response.answer


def test_anomaly_question_with_compatible_pair_reports_no_threshold_match() -> None:
    previous = _company_world().model_copy(
        update={
            "metadata": _company_world().metadata.model_copy(
                update={"snapshot_id": "snapshot-previous", "game_date": 10}
            )
        }
    )
    compilation = _compile(
        "Are there any unusual changes?",
        comparison=previous.metadata.snapshot_id,
    )
    assert compilation.request is not None

    response = AnalysisService(default_analyzer_registry()).analyze(
        compilation.request, _company_world(), previous
    )

    assert response.status is AnalysisStatus.COMPLETED
    assert response.answer == "No observed change met the bounded anomaly thresholds."
    assert response.presentation is not None
    assert "fixed change alerts" in (response.presentation.limitation or "")


def test_company_direction_question_does_not_overclaim_from_one_change() -> None:
    previous = _company_world().model_copy(
        update={
            "metadata": _company_world().metadata.model_copy(
                update={"snapshot_id": "snapshot-previous", "game_date": 10}
            )
        }
    )
    current = _company_world().model_copy(
        update={
            "changes_from_snapshot_id": "snapshot-previous",
            "changes": (
                FieldChanged(
                    entity_type="company",
                    entity_id="company-1",
                    field="cash",
                    before=1_000_000,
                    after=2_000_000,
                ),
            ),
        }
    )
    compilation = _compile("Is the company improving?", comparison="snapshot-previous")
    assert compilation.request is not None

    response = AnalysisService(default_analyzer_registry()).analyze(
        compilation.request, current, previous
    )

    assert response.answer.startswith("I cannot determine the company's overall direction")


def test_best_train_ranking_keeps_type_metric_period_and_direction() -> None:
    compilation = _compile("Which trains performed best last year?")
    assert compilation.request is not None
    request = compilation.request
    assert request.analysis_type is AnalysisType.VEHICLE_PERFORMANCE
    assert request.filters[0].values == ("rail",)
    assert request.ranking is not None
    assert request.ranking.metric is RankingMetric.PROFIT_LAST_YEAR
    assert request.ranking.direction is RankingDirection.DESCENDING
    assert request.answer_intent is not None
    assert request.answer_intent.period is AnswerPeriod.LAST_YEAR


def test_positive_ranking_presents_the_actual_top_entity() -> None:
    profitable = Vehicle(
        id="rail-best",
        type="rail",
        name="Best",
        age_days=10,
        profit_this_year=500,
        profit_last_year=1_000,
        running_state="running",
        coordinates=None,
        in_depot=False,
        owner_id="company-1",
    )
    losing = profitable.model_copy(
        update={"id": "rail-loss", "name": "Loss", "profit_last_year": -100}
    )
    compilation = _compile("Which trains performed best last year?")
    assert compilation.request is not None

    response = AnalysisService(default_analyzer_registry()).analyze(
        compilation.request,
        snapshot(vehicles=(profitable, losing)),
    )

    assert response.status is AnalysisStatus.COMPLETED_WITH_LIMITATIONS
    assert "Best" in response.answer
    assert response.presentation is not None
    assert response.presentation.evaluated_count == 2
    assert response.presentation.excluded_count == 0


def test_route_losing_vehicle_request_is_not_changed_to_total_vehicle_count() -> None:
    compilation = _compile("Which routes have the most losing vehicles?")
    assert compilation.request is not None
    assert compilation.request.ranking is not None
    assert compilation.request.ranking.metric is RankingMetric.ROUTE_NEGATIVE_VEHICLE_COUNT
    assert compilation.request.answer_intent is not None
    assert (
        compilation.request.answer_intent.requested_metric
        is AnswerMetric.ROUTE_NEGATIVE_VEHICLE_COUNT
    )


def test_idle_no_result_names_the_deterministic_criteria() -> None:
    running = Vehicle(
        id="running",
        type="road",
        name="Running",
        age_days=10,
        profit_this_year=100,
        profit_last_year=100,
        running_state="running",
        coordinates=None,
        in_depot=False,
        owner_id="company-1",
    )
    compilation = _compile("Are any vehicles sitting idle?")
    assert compilation.request is not None
    response = AnalysisService(default_analyzer_registry()).analyze(
        compilation.request, snapshot(vehicles=(running,))
    )

    assert response.answer == "No idle vehicles were detected in the observed company fleet."
    assert response.presentation is not None
    assert "in a depot" in (response.presentation.limitation or "")
    assert response.presentation.evaluated_count == 1


def test_context_free_route_follow_up_clarifies_and_single_route_context_resolves() -> None:
    compiler = DeterministicAnalysisCompiler()
    missing = asyncio.run(compiler.compile("Why is this route losing money?"))
    assert missing.clarification is not None

    resolved = asyncio.run(
        compiler.compile(
            "Why is this route losing money?",
            context=AnalysisCompilerContext(
                prior_analysis_id="analysis:0123456789abcdef0123",
                focus_entities=(
                    AnalysisEntityContext(
                        subject_type=AnalysisSubjectType.ROUTE,
                        canonical_id="route-1",
                        alias="R-001",
                    ),
                ),
            ),
        )
    )
    assert resolved.request is not None
    assert resolved.request.subject_type is AnalysisSubjectType.ROUTE
    assert resolved.request.subject_ids == ("route-1",)
    assert resolved.request.resolved_reference is not None
    assert resolved.request.resolved_reference.entity_id == "route-1"


def test_ambiguous_vehicle_reference_requires_clarification() -> None:
    result = asyncio.run(
        DeterministicAnalysisCompiler().compile(
            "Why did you flag that vehicle?",
            context=AnalysisCompilerContext(
                prior_analysis_id="analysis:0123456789abcdef0123",
                focus_entities=(
                    AnalysisEntityContext(
                        subject_type=AnalysisSubjectType.VEHICLE,
                        canonical_id="vehicle-1",
                        alias="V-001",
                    ),
                    AnalysisEntityContext(
                        subject_type=AnalysisSubjectType.VEHICLE,
                        canonical_id="vehicle-2",
                        alias="V-002",
                    ),
                ),
            ),
        )
    )

    assert result.clarification is not None
    assert "Which vehicle" in result.clarification


def test_selected_recommendation_is_supported_by_the_decisive_finding() -> None:
    losing = Vehicle(
        id="loss",
        type="road",
        name="Loss",
        age_days=10,
        profit_this_year=-100,
        profit_last_year=-100,
        running_state="running",
        coordinates=None,
        in_depot=False,
        owner_id="company-1",
    )
    compilation = _compile("Which vehicles are losing the most money?")
    assert compilation.request is not None
    response = AnalysisService(default_analyzer_registry()).analyze(
        compilation.request, snapshot(vehicles=(losing,))
    )
    assert response.presentation is not None
    decisive = response.presentation.decisive_finding_id
    selected = response.presentation.recommendation_id
    recommendation = next(
        item for item in response.recommendations if item.recommendation_id == selected
    )
    assert decisive in recommendation.supporting_finding_ids
    rendered = render_analysis(response, snapshot=snapshot(vehicles=(losing,)))
    assert recommendation.title in rendered
    assert rendered.count(recommendation.rationale) == 0


def test_worst_vehicle_answer_names_the_vehicle_and_loss_first() -> None:
    losing = Vehicle(
        id="loss",
        type="road",
        name="Loss Leader",
        age_days=10,
        profit_this_year=-100,
        profit_last_year=-351,
        running_state="running",
        coordinates=None,
        in_depot=False,
        owner_id="company-1",
    )
    compilation = _compile("Which vehicle lost the most money last year?")
    assert compilation.request is not None
    response = AnalysisService(default_analyzer_registry()).analyze(
        compilation.request, snapshot(vehicles=(losing,))
    )

    assert response.answer == "Loss Leader (V-001) ranks lowest, losing £351 last year."


def test_vehicle_type_dragging_question_corrects_a_false_loss_premise() -> None:
    road = Vehicle(
        id="road",
        type="road",
        name="Road Earner",
        age_days=10,
        profit_this_year=100,
        profit_last_year=100,
        running_state="running",
        coordinates=None,
        in_depot=False,
        owner_id="company-1",
    )
    rail = road.model_copy(
        update={"id": "rail", "type": "rail", "name": "Rail Earner", "profit_last_year": 200}
    )
    compilation = _compile("Which vehicle type is dragging down the company?")
    assert compilation.request is not None
    response = AnalysisService(default_analyzer_registry()).analyze(
        compilation.request, snapshot(vehicles=(road, rail))
    )

    assert response.answer == (
        "No vehicle type lost money overall; road vehicles had the lowest aggregate "
        "last-year profit at £100."
    )
    rendered = render_analysis(response, snapshot=snapshot(vehicles=(road, rail)))
    assert "Road vehicles: vehicle type aggregate profit is £100." in rendered
