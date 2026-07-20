import asyncio

import pytest
from pydantic import ValidationError

from sim_pilot.analysis.compiler import (
    AnalysisCompilation,
    AnalysisCompilerContext,
    DeterministicAnalysisCompiler,
    ScriptedAnalysisCompiler,
    normalize_provider_compilation,
)
from sim_pilot.analysis.contracts import (
    AnalysisRequest,
    AnalysisSubjectType,
    AnalysisType,
    AnswerConcept,
    AnswerIntent,
    AnswerKind,
    AnswerPeriod,
    QuestionForm,
    RankingDirection,
    RankingMetric,
)
from sim_pilot.analysis.errors import AnalysisRequestError
from sim_pilot.analysis.prompt import ANALYSIS_COMPILER_PROMPT


def compile_question(question: str) -> AnalysisCompilation:
    return asyncio.run(DeterministicAnalysisCompiler().compile(question))


def test_deterministic_compiler_maps_informal_vehicle_question() -> None:
    result = compile_question("Which trains made the least money last year?")
    assert result.request is not None
    assert result.request.analysis_type is AnalysisType.VEHICLE_PERFORMANCE
    assert result.request.filters[0].values == ("rail",)
    assert result.request.ranking is not None
    assert result.request.ranking.metric is RankingMetric.PROFIT_LAST_YEAR
    assert result.request.ranking.direction is RankingDirection.ASCENDING


def test_deterministic_compiler_ranks_profitable_routes_descending() -> None:
    result = compile_question("Which route makes the most money?")
    assert result.request is not None
    assert result.request.analysis_type is AnalysisType.ROUTE_PERFORMANCE
    assert result.request.ranking is not None
    assert result.request.ranking.metric is RankingMetric.ROUTE_AGGREGATE_PROFIT
    assert result.request.ranking.direction is RankingDirection.DESCENDING


@pytest.mark.parametrize(
    ("question", "subject"),
    (
        ("Which station should I inspect first?", AnalysisSubjectType.STATION),
        ("Which vehicle should I inspect first?", AnalysisSubjectType.VEHICLE),
        ("Which route should I inspect first?", AnalysisSubjectType.ROUTE),
    ),
)
def test_priority_questions_preserve_named_entity_class(
    question: str, subject: AnalysisSubjectType
) -> None:
    result = compile_question(question)
    assert result.request is not None
    assert result.request.analysis_type is AnalysisType.PRIORITY_REVIEW
    assert result.request.subject_type is subject
    assert result.request.ranking is not None
    assert result.request.ranking.metric is RankingMetric.PRIORITY_SCORE


@pytest.mark.parametrize(
    ("question", "subject", "metric"),
    (
        ("Which towns gained population?", AnalysisSubjectType.TOWN, RankingMetric.POPULATION),
        (
            "Did profitable vehicles become unprofitable?",
            AnalysisSubjectType.VEHICLE,
            RankingMetric.PROFIT_LAST_YEAR,
        ),
    ),
)
def test_typed_comparisons_preserve_subject_and_metric(
    question: str,
    subject: AnalysisSubjectType,
    metric: RankingMetric,
) -> None:
    result = compile_question(question)
    assert result.request is not None
    assert result.request.analysis_type is AnalysisType.WORLD_CHANGES
    assert result.request.subject_type is subject
    assert result.request.answer_intent is not None
    assert result.request.answer_intent.question_forms == (QuestionForm.COMPARISON,)
    assert result.request.answer_intent.requested_metric is metric
    assert result.request.answer_intent.period is AnswerPeriod.BETWEEN_SNAPSHOTS


def test_deterministic_compiler_uses_supplied_comparison_context() -> None:
    result = asyncio.run(
        DeterministicAnalysisCompiler().compile(
            "What changed since before?",
            context=AnalysisCompilerContext(comparison_snapshot_id="snapshot-before"),
        )
    )
    assert result.request is not None
    assert result.request.analysis_type is AnalysisType.WORLD_CHANGES
    assert result.request.comparison_snapshot_id == "snapshot-before"


@pytest.mark.parametrize(
    ("question", "outcome"),
    (
        ("Tell me exactly what will be profitable in ten years", "unsupported"),
        ("Why did this train crash?", "unsupported"),
        ("Fix my worst route", "unsupported"),
        ("Which route is bad?", "clarification"),
        ("Are there unusual changes?", "request"),
        ("What should I do?", "clarification"),
        ("Is this okay?", "clarification"),
    ),
)
def test_compiler_is_honest_about_unsupported_and_ambiguous_questions(
    question: str, outcome: str
) -> None:
    result = compile_question(question)
    assert (result.unsupported_reason is not None) is (outcome == "unsupported")
    assert (result.clarification is not None) is (outcome == "clarification")
    assert (result.request is not None) is (outcome == "request")


def test_compilation_requires_exactly_one_outcome() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        AnalysisCompilation(clarification="Which route?", unsupported_reason="Unsupported")


def test_scripted_compiler_exhaustion_is_explicit() -> None:
    compiler = ScriptedAnalysisCompiler((AnalysisCompilation(clarification="More detail"),))
    asyncio.run(compiler.compile("First"))
    with pytest.raises(RuntimeError, match="exhausted"):
        asyncio.run(compiler.compile("Second"))


def test_provider_compilation_fills_missing_typed_answer_intent() -> None:
    normalized = normalize_provider_compilation(
        AnalysisCompilation(
            request=AnalysisRequest(
                analysis_type=AnalysisType.FINANCIAL_SUMMARY,
                question="Am I carrying too much debt?",
            )
        )
    )
    assert normalized.request is not None
    assert normalized.request.answer_intent is not None
    assert normalized.request.answer_intent.concept is AnswerConcept.DEBT


def test_provider_compilation_rejects_wrong_analyzer_for_exact_financial_question() -> None:
    with pytest.raises(AnalysisRequestError, match="requiring financial_summary"):
        normalize_provider_compilation(
            AnalysisCompilation(
                request=AnalysisRequest(
                    analysis_type=AnalysisType.COMPANY_HEALTH,
                    question="Am I carrying too much debt?",
                )
            )
        )


def test_provider_compilation_rejects_wrong_core_answer_semantics() -> None:
    with pytest.raises(AnalysisRequestError, match="answer intent"):
        normalize_provider_compilation(
            AnalysisCompilation(
                request=AnalysisRequest(
                    analysis_type=AnalysisType.FINANCIAL_SUMMARY,
                    question="How much cash do I have?",
                    answer_intent=AnswerIntent(
                        concept=AnswerConcept.DEBT,
                        kind=AnswerKind.FACT,
                    ),
                )
            )
        )


def test_provider_prompt_delegates_answer_intent_to_trusted_normalization() -> None:
    assert "Set\nanswer_intent to null" in ANALYSIS_COMPILER_PROMPT
    assert "trusted deterministic normalizer" in ANALYSIS_COMPILER_PROMPT
