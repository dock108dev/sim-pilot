import asyncio

from sim_pilot.analysis.compiler import AnalysisCompilation, ScriptedAnalysisCompiler
from sim_pilot.analysis.contracts import (
    AnalysisExplanation,
    AnalysisExplanationStatement,
    AnalysisRequest,
    AnalysisType,
    ExplanationClaimType,
    ExplanationMetricReference,
)
from sim_pilot.analysis.explanation import ScriptedExplanationProvider
from sim_pilot.analysis.query import AnalysisQueryService
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from tests.analysis.helpers import snapshot


def query_service() -> AnalysisQueryService:
    return AnalysisQueryService(AnalysisService(default_analyzer_registry()))


def request() -> AnalysisRequest:
    return AnalysisRequest(analysis_type=AnalysisType.FINANCIAL_SUMMARY, question="Finances?")


def test_faithful_explanation_is_attached() -> None:
    deterministic = AnalysisService(default_analyzer_registry()).analyze(request(), snapshot())
    cash = next(item for item in deterministic.findings if item.metric_name == "cash")
    explanation = AnalysisExplanation(
        statements=(
            AnalysisExplanationStatement(
                claim_type=ExplanationClaimType.SUMMARY,
                text="Observed cash is 100.",
                finding_ids=(cash.finding_id,),
                entity_ids=("company-1",),
                metric_references=(
                    ExplanationMetricReference(
                        finding_id=cash.finding_id,
                        metric_name="cash",
                        metric_value=100,
                    ),
                ),
            ),
        )
    )
    compiler = ScriptedAnalysisCompiler((AnalysisCompilation(request=request()),))
    _, response = asyncio.run(
        query_service().ask(
            "Finances?",
            snapshot(),
            compiler=compiler,
            explanation_provider=ScriptedExplanationProvider((explanation,)),
        )
    )
    assert response is not None
    assert response.explanation == explanation


def test_invented_metric_falls_back_to_deterministic_output() -> None:
    deterministic = AnalysisService(default_analyzer_registry()).analyze(request(), snapshot())
    cash = next(item for item in deterministic.findings if item.metric_name == "cash")
    invalid = AnalysisExplanation(
        statements=(
            AnalysisExplanationStatement(
                claim_type=ExplanationClaimType.SUMMARY,
                text="Invented cash value.",
                finding_ids=(cash.finding_id,),
                metric_references=(
                    ExplanationMetricReference(
                        finding_id=cash.finding_id,
                        metric_name="cash",
                        metric_value=999,
                    ),
                ),
            ),
        )
    )
    response = asyncio.run(
        query_service().analyze_request(
            request(),
            snapshot(),
            explanation_provider=ScriptedExplanationProvider((invalid,)),
        )
    )
    assert response.explanation is None
    assert any("rejected" in item for item in response.limitations)
