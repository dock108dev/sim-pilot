"""Bounded explanation-provider input and reference validation."""

from __future__ import annotations

from collections import deque
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.analysis.contracts import (
    AnalysisExplanation,
    AnalysisExplanationStatement,
    AnalysisFinding,
    AnalysisRecommendation,
    AnalysisRequest,
    AnalysisResponse,
    ExplanationClaimType,
    FindingSeverity,
)
from sim_pilot.analysis.errors import AnalysisInputError


class ExplanationStyle(StrEnum):
    COMPACT = "compact"
    COACH = "coach"
    TECHNICAL = "technical"


class ExplanationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    question: str = Field(min_length=1, max_length=2_000)
    request: AnalysisRequest
    findings: tuple[AnalysisFinding, ...] = Field(max_length=20)
    recommendations: tuple[AnalysisRecommendation, ...] = Field(max_length=20)
    limitations: tuple[str, ...] = Field(max_length=50)
    style: ExplanationStyle = ExplanationStyle.COMPACT


class ExplanationProvider(Protocol):
    async def explain(self, context: ExplanationInput) -> AnalysisExplanation: ...


class ScriptedExplanationProvider:
    def __init__(self, explanations: tuple[AnalysisExplanation, ...]) -> None:
        self._explanations = deque(explanations)

    async def explain(self, context: ExplanationInput) -> AnalysisExplanation:
        del context
        if not self._explanations:
            raise RuntimeError("scripted explanation provider exhausted")
        return self._explanations.popleft()


def explanation_input(
    response: AnalysisResponse,
    *,
    style: ExplanationStyle = ExplanationStyle.COMPACT,
) -> ExplanationInput:
    return ExplanationInput(
        question=response.request.question,
        request=response.request,
        findings=response.findings,
        recommendations=response.recommendations,
        limitations=response.limitations,
        style=style,
    )


def validate_explanation(
    explanation: AnalysisExplanation, response: AnalysisResponse
) -> AnalysisExplanation:
    findings = {item.finding_id: item for item in response.findings}
    recommendations = {item.recommendation_id for item in response.recommendations}
    entities = {
        evidence.entity_id
        for finding in response.findings
        for evidence in finding.evidence
        if evidence.entity_id is not None
    }
    critical_findings = {
        item.finding_id
        for item in response.findings
        if item.severity is FindingSeverity.CRITICAL and item.limitations
    }
    acknowledged_limitations: set[str] = set()
    for statement in explanation.statements:
        if not set(statement.finding_ids).issubset(findings):
            raise AnalysisInputError("explanation references an unknown finding")
        if not set(statement.recommendation_ids).issubset(recommendations):
            raise AnalysisInputError("explanation references an unknown recommendation")
        if not set(statement.entity_ids).issubset(entities):
            raise AnalysisInputError("explanation references an unknown entity")
        if (
            statement.recommendation_ids
            and statement.claim_type is not ExplanationClaimType.RECOMMENDATION
        ):
            raise AnalysisInputError(
                "an explanation recommendation must be labeled as a recommendation"
            )
        if statement.claim_type is ExplanationClaimType.LIMITATION:
            acknowledged_limitations.update(statement.finding_ids)
        for reference in statement.metric_references:
            finding = findings.get(reference.finding_id)
            if finding is None:
                raise AnalysisInputError("metric reference cites an unknown finding")
            if finding.metric_name != reference.metric_name:
                raise AnalysisInputError("explanation changes an authoritative metric name")
            if finding.metric_value != reference.metric_value:
                raise AnalysisInputError("explanation changes an authoritative metric value")
    if not critical_findings.issubset(acknowledged_limitations):
        raise AnalysisInputError("explanation omits a critical finding limitation")
    return explanation


def retain_valuable_explanation(
    explanation: AnalysisExplanation,
    response: AnalysisResponse,
) -> AnalysisExplanation | None:
    """Suppress provider prose that only repeats the deterministic answer."""
    presentation = response.presentation
    base_texts = {
        _normalized(response.answer),
        *(_normalized(item.title) for item in response.findings),
        *(_normalized(item.summary) for item in response.findings),
        *(_normalized(item.rationale) for item in response.recommendations),
        *(_normalized(item) for item in response.limitations),
    }
    if presentation is not None and presentation.limitation is not None:
        base_texts.add(_normalized(presentation.limitation))
    selected: list[AnalysisExplanationStatement] = []
    for statement in explanation.statements:
        text = _normalized(statement.text)
        if not text or any(
            text == base or text in base or base in text for base in base_texts if base
        ):
            continue
        if statement.claim_type is ExplanationClaimType.LIMITATION:
            selected.append(statement)
            continue
        if statement.claim_type is ExplanationClaimType.RECOMMENDATION:
            decisive = None if presentation is None else presentation.decisive_finding_id
            selected_recommendation = (
                None if presentation is None else presentation.recommendation_id
            )
            if (
                decisive is not None
                and decisive in statement.finding_ids
                and selected_recommendation is not None
                and selected_recommendation in statement.recommendation_ids
            ):
                selected.append(statement)
            continue
        if len(statement.finding_ids) >= 2:
            selected.append(statement)
    if not selected:
        return None
    return AnalysisExplanation(statements=tuple(selected))


def _normalized(value: str) -> str:
    return " ".join(value.casefold().rstrip(".").split())
