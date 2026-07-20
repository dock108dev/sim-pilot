"""Bounded explanation-provider input and reference validation."""

from __future__ import annotations

import re
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
    InspectionGuidance,
    InspectionGuidanceStatus,
    QuestionForm,
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
    inspection_guidance: InspectionGuidance | None = None
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
        inspection_guidance=(
            None if response.presentation is None else response.presentation.inspection_guidance
        ),
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
    authoritative_numbers = _numbers(
        " ".join(
            (
                response.answer,
                *(item.title for item in response.findings),
                *(item.summary for item in response.findings),
                *(str(item.metric_value) for item in response.findings),
                *(item.rationale for item in response.recommendations),
            )
        )
    )
    for statement in explanation.statements:
        if re.search(r"(?i)\b(proves?|is caused by|is due to|guarantees?)\b", statement.text):
            raise AnalysisInputError("explanation asserts unsupported causal certainty")
        if not _numbers(statement.text).issubset(authoritative_numbers):
            raise AnalysisInputError("explanation introduces an unsupported number")
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
        if statement.claim_type is ExplanationClaimType.RECOMMENDATION:
            presentation = response.presentation
            if presentation is None:
                raise AnalysisInputError("explanation recommendation has no selected guidance")
            guidance = presentation.inspection_guidance
            if guidance.status is not InspectionGuidanceStatus.RECOMMENDED:
                raise AnalysisInputError(
                    "explanation recommendation contradicts unavailable guidance"
                )
            assert guidance.target_label is not None
            if guidance.target_label.casefold() not in statement.text.casefold():
                raise AnalysisInputError("explanation recommendation changes the inspection target")
            if guidance.target_entity_id is not None and set(statement.entity_ids) != {
                guidance.target_entity_id
            }:
                raise AnalysisInputError("explanation recommendation changes the inspection entity")
            if not set(guidance.supporting_finding_ids).issubset(statement.finding_ids):
                raise AnalysisInputError("explanation recommendation changes its evidence basis")
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
    if presentation is not None:
        guidance = presentation.inspection_guidance
        base_texts.update(
            _normalized(value)
            for value in (
                guidance.observation,
                guidance.diagnostic_value,
                guidance.unavailable_reason,
            )
            if value is not None
        )
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
    if sum(len(item.text.split()) for item in selected) > 80:
        return None
    return AnalysisExplanation(statements=tuple(selected))


def should_invoke_explanation(response: AnalysisResponse) -> bool:
    """Gate model use to answers where synthesis can add material value."""
    if response.status.value in {
        "insufficient_data",
        "clarification_required",
        "unsupported",
        "failed",
    }:
        return False
    intent = response.request.answer_intent
    if intent is None or response.presentation is None:
        return False
    forms = set(intent.question_forms)
    if forms & {QuestionForm.QUANTITY, QuestionForm.EXISTENCE, QuestionForm.RANKING}:
        return False
    return bool(
        len(response.findings) >= 2
        and forms
        & {
            QuestionForm.CAUSE,
            QuestionForm.DRILL_DOWN,
            QuestionForm.SUMMARY,
            QuestionForm.RECOMMENDATION,
        }
    )


def _normalized(value: str) -> str:
    return " ".join(value.casefold().rstrip(".").split())


def _numbers(value: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)*%?", value))
