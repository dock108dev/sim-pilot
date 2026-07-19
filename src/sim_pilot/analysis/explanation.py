"""Bounded explanation-provider input and reference validation."""

from __future__ import annotations

from collections import deque
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.analysis.contracts import (
    AnalysisExplanation,
    AnalysisFinding,
    AnalysisRecommendation,
    AnalysisRequest,
    AnalysisResponse,
)
from sim_pilot.analysis.errors import AnalysisInputError


class ExplanationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    question: str = Field(min_length=1, max_length=2_000)
    request: AnalysisRequest
    findings: tuple[AnalysisFinding, ...] = Field(max_length=20)
    recommendations: tuple[AnalysisRecommendation, ...] = Field(max_length=20)
    limitations: tuple[str, ...] = Field(max_length=50)
    tone: str = Field(default="concise", min_length=1, max_length=40)


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


def explanation_input(response: AnalysisResponse, *, tone: str = "concise") -> ExplanationInput:
    return ExplanationInput(
        question=response.request.question,
        request=response.request,
        findings=response.findings,
        recommendations=response.recommendations,
        limitations=response.limitations,
        tone=tone,
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
    for statement in explanation.statements:
        if not set(statement.finding_ids).issubset(findings):
            raise AnalysisInputError("explanation references an unknown finding")
        if not set(statement.recommendation_ids).issubset(recommendations):
            raise AnalysisInputError("explanation references an unknown recommendation")
        if not set(statement.entity_ids).issubset(entities):
            raise AnalysisInputError("explanation references an unknown entity")
        for reference in statement.metric_references:
            finding = findings.get(reference.finding_id)
            if finding is None:
                raise AnalysisInputError("metric reference cites an unknown finding")
            if finding.metric_name != reference.metric_name:
                raise AnalysisInputError("explanation changes an authoritative metric name")
            if finding.metric_value != reference.metric_value:
                raise AnalysisInputError("explanation changes an authoritative metric value")
    return explanation
