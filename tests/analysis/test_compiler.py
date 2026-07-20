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
    AnalysisType,
    AnswerConcept,
    RankingDirection,
    RankingMetric,
)
from sim_pilot.analysis.errors import AnalysisRequestError


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
        ("Are there unusual changes?", "clarification"),
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
