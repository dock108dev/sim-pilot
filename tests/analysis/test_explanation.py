import asyncio

import pytest

from sim_pilot.analysis.compiler import (
    AnalysisCompilation,
    DeterministicAnalysisCompiler,
    ScriptedAnalysisCompiler,
)
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
from sim_pilot.domain.world import Company, Vehicle
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
    assert response.explanation_value.value == "not_invoked"
    assert not any("rejected" in item for item in response.limitations)


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
                text="Inspect Company because this is the selected company-level loss signal.",
                finding_ids=(finding_id,),
                recommendation_ids=(recommendation_id,),
                entity_ids=("company-1",),
            ),
        )
    )

    retained = retain_valuable_explanation(validate_explanation(explanation, response), response)

    assert retained == explanation


def test_explanation_with_unsupported_causal_certainty_is_rejected() -> None:
    response = AnalysisService(default_analyzer_registry()).analyze(request(), snapshot())
    finding = response.findings[0]
    explanation = AnalysisExplanation(
        statements=(
            AnalysisExplanationStatement(
                claim_type=ExplanationClaimType.SUMMARY,
                text="This result proves the route has insufficient demand.",
                finding_ids=(finding.finding_id,),
            ),
        )
    )

    with pytest.raises(AnalysisInputError, match="unsupported causal certainty"):
        validate_explanation(explanation, response)


def test_explanation_recommendation_that_changes_target_is_rejected() -> None:
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
                text="Inspect another operator next.",
                finding_ids=(finding_id,),
                recommendation_ids=(recommendation_id,),
                entity_ids=("company-1",),
            ),
        )
    )

    with pytest.raises(AnalysisInputError, match="changes the inspection target"):
        validate_explanation(explanation, response)


def test_causal_multi_finding_answer_can_invoke_and_retain_useful_synthesis() -> None:
    vehicles = tuple(
        Vehicle(
            id=f"vehicle-{index}",
            type="road",
            name=f"Vehicle {index}",
            age_days=20,
            profit_this_year=-10,
            profit_last_year=-10,
            running_state="running",
            coordinates=None,
            in_depot=False,
            owner_id="company-1",
        )
        for index in range(4)
    )
    world = snapshot(
        company=Company(
            id="company-1",
            name="Company",
            cash=100,
            loan=0,
            income=1_000,
            expenses=-100,
        ),
        vehicles=vehicles,
    )
    compilation = asyncio.run(DeterministicAnalysisCompiler().compile("Why am I losing money?"))
    assert compilation.request is not None
    deterministic = AnalysisService(default_analyzer_registry()).analyze(compilation.request, world)
    finding_ids = tuple(item.finding_id for item in deterministic.findings[:2])
    critical_id = next(
        item.finding_id
        for item in deterministic.findings
        if item.severity is FindingSeverity.CRITICAL
    )
    explanation = AnalysisExplanation(
        statements=(
            AnalysisExplanationStatement(
                claim_type=ExplanationClaimType.SUMMARY,
                text=(
                    "The company-level result and vehicle-level losses describe different "
                    "profitability scopes."
                ),
                finding_ids=finding_ids,
            ),
            AnalysisExplanationStatement(
                claim_type=ExplanationClaimType.LIMITATION,
                text="Vehicle-level losses can include deliberately subsidized service.",
                finding_ids=(critical_id,),
            ),
        )
    )

    response = asyncio.run(
        query_service().analyze_request(
            compilation.request,
            world,
            explanation_provider=ScriptedExplanationProvider((explanation,)),
        )
    )

    assert response.explanation == explanation
    assert response.explanation_value.value == "improved_answer"
