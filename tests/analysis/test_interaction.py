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
from sim_pilot.domain.world import Company, Vehicle
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
    assert response.answer.startswith("Insufficient data:")
    assert "no evaluated typed change evidence" in response.answer


def test_anomaly_question_without_evaluated_delta_evidence_is_insufficient() -> None:
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

    assert response.status is AnalysisStatus.INSUFFICIENT_DATA
    assert "no evaluated typed change evidence" in response.answer


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


def test_ranking_does_not_present_a_non_top_retained_finding() -> None:
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

    assert response.status is AnalysisStatus.INSUFFICIENT_DATA
    assert "no evaluated finding matches" in response.answer
    assert response.presentation is not None
    assert response.presentation.evaluated_count == 2
    assert response.presentation.excluded_count == 0


def test_route_losing_vehicle_request_is_not_changed_to_total_vehicle_count() -> None:
    compilation = _compile("Which routes have the most losing vehicles?")
    assert compilation.request is not None
    assert compilation.request.ranking is None
    assert compilation.request.answer_intent is not None
    assert compilation.request.answer_intent.requested_metric is AnswerMetric.NEGATIVE_VEHICLE_COUNT


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
                focus_entities=(
                    AnalysisEntityContext(
                        subject_type=AnalysisSubjectType.ROUTE,
                        canonical_id="route-1",
                        alias="R-001",
                    ),
                )
            ),
        )
    )
    assert resolved.request is not None
    assert resolved.request.subject_type is AnalysisSubjectType.ROUTE
    assert resolved.request.subject_ids == ("route-1",)


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
