"""Offline founder-question dataset contracts and result records."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from sim_pilot.analysis.contracts import AnalysisStatus, AnalysisSubjectType, AnalysisType


class FounderQuestionCategory(StrEnum):
    COMPANY_HEALTH = "company_health"
    VEHICLES = "vehicles"
    STATIONS = "stations"
    ROUTES = "routes"
    TOWNS_INDUSTRIES = "towns_industries"
    CHANGES_ANOMALIES = "changes_anomalies"
    DRILL_DOWN = "drill_down"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class FounderIntelligenceCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    case_id: str = Field(min_length=1)
    category: FounderQuestionCategory
    question: str = Field(min_length=1)
    expected_analysis_types: tuple[AnalysisType, ...] = Field(max_length=3)
    expected_statuses: tuple[AnalysisStatus, ...] = Field(min_length=1)
    required_evidence_types: tuple[AnalysisSubjectType, ...] = ()
    requires_comparison: bool = False
    manual_rating: Literal["correct", "acceptable", "annoying", "incorrect", "unsafe"] | None = None
    revealed_nonobvious_information: Literal["yes", "partially", "no"] | None = None
    would_use_during_gameplay: Literal["yes", "maybe", "no"] | None = None
    reviewer_notes: str | None = None

    @model_validator(mode="after")
    def subjective_fields_must_start_empty(self) -> Self:
        if any(
            item is not None
            for item in (
                self.manual_rating,
                self.revealed_nonobvious_information,
                self.would_use_during_gameplay,
                self.reviewer_notes,
            )
        ):
            raise ValueError("founder question fixtures must not prefill subjective review fields")
        return self


class FounderQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expected: str = Field(min_length=1)


class FounderEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    case_id: str = Field(min_length=1)
    compilation_correct: bool | None = None
    analyzer_selection_correct: bool | None = None
    evidence_correct: bool | None = None
    finding_useful: bool | None = None
    recommendation_useful: bool | None = None
    unsupported_behavior_correct: bool | None = None
    explanation_faithful: bool | None = None
    latency_seconds: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    deterministic_contribution: str = "not_run"
    model_contribution: str = "not_run"
    manual_rating: Literal["correct", "acceptable", "annoying", "incorrect", "unsafe"] | None = None
    revealed_nonobvious_information: Literal["yes", "partially", "no"] | None = None
    reviewer_notes: str = ""


def load_founder_questions(path: Path) -> tuple[FounderQuestion, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(TypeAdapter(list[FounderQuestion]).validate_python(payload, strict=True))


def load_founder_results(path: Path) -> tuple[FounderEvaluationResult, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(TypeAdapter(list[FounderEvaluationResult]).validate_python(payload, strict=True))


def load_founder_intelligence_cases(path: Path) -> tuple[FounderIntelligenceCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = tuple(TypeAdapter(list[FounderIntelligenceCase]).validate_python(payload, strict=False))
    identifiers = [item.case_id for item in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("founder intelligence case IDs must be unique")
    return cases
