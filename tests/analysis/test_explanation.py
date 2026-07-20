import asyncio

import pytest

from sim_pilot.analysis.compiler import AnalysisCompilation, ScriptedAnalysisCompiler
from sim_pilot.analysis.contracts import (
    AnalysisExplanation,
    AnalysisExplanationStatement,
    AnalysisRequest,
    AnalysisType,
    ExplanationClaimType,
    ExplanationMetricReference,
    FindingSeverity,
)
from sim_pilot.analysis.errors import AnalysisInputError
from sim_pilot.analysis.explanation import (
    ScriptedExplanationProvider,
    retain_valuable_explanation,
    validate_explanation,
)
from sim_pilot.analysis.query import AnalysisQueryService
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.domain.world import Company
from tests.analysis.helpers import snapshot


def query_service() -> AnalysisQueryService:
    return AnalysisQueryService(AnalysisService(default_analyzer_registry()))


def request() -> AnalysisRequest:
    return AnalysisRequest(analysis_type=AnalysisType.FINANCIAL_SUMMARY, question="Finances?")


def test_faithful_but_redundant_explanation_is_suppressed() -> None:
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
    assert response.explanation is None


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


def test_explanation_omitting_critical_finding_limitation_is_rejected() -> None:
    deterministic = AnalysisService(default_analyzer_registry()).analyze(request(), snapshot())
    cash = next(item for item in deterministic.findings if item.metric_name == "cash")
    critical = cash.model_copy(
        update={
            "severity": FindingSeverity.CRITICAL,
            "limitations": ("Cash excludes unobserved infrastructure liabilities.",),
        }
    )
    response = deterministic.model_copy(update={"findings": (critical,)})
    explanation = AnalysisExplanation(
        statements=(
            AnalysisExplanationStatement(
                claim_type=ExplanationClaimType.SUMMARY,
                text="Cash is critical.",
                finding_ids=(critical.finding_id,),
            ),
        )
    )
    with pytest.raises(AnalysisInputError, match="omits a critical"):
        validate_explanation(explanation, response)


def test_explanation_that_connects_selected_finding_and_recommendation_is_retained() -> None:
    response = AnalysisService(default_analyzer_registry()).analyze(
        AnalysisRequest(analysis_type=AnalysisType.COMPANY_HEALTH, question="Health?"),
        snapshot(
            company=Company(
                id="company-1",
                name="Company",
                cash=10,
                loan=0,
                income=10,
                expenses=-100,
            )
        ),
    )
    assert response.presentation is not None
    finding_id = response.presentation.decisive_finding_id
    recommendation_id = response.presentation.recommendation_id
    assert finding_id is not None
    assert recommendation_id is not None
    explanation = AnalysisExplanation(
        statements=(
            AnalysisExplanationStatement(
                claim_type=ExplanationClaimType.RECOMMENDATION,
                text="Start here because this is the selected company-level loss signal.",
                finding_ids=(finding_id,),
                recommendation_ids=(recommendation_id,),
            ),
        )
    )

    retained = retain_valuable_explanation(validate_explanation(explanation, response), response)

    assert retained == explanation
