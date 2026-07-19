"""Offline founder-question dataset contracts and result records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


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
