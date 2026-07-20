"""Provider-free analyzer interface and normalized result."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.analysis.contracts import (
    AnalysisFinding,
    AnalysisPopulation,
    AnalysisRecommendation,
    AnalysisRequest,
    AnalysisStatus,
    AnalysisType,
)
from sim_pilot.domain.world import WorldSnapshot


class AnalyzerResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    status: AnalysisStatus
    answer: str = Field(min_length=1)
    findings: tuple[AnalysisFinding, ...] = ()
    recommendations: tuple[AnalysisRecommendation, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    unsupported_parts: tuple[str, ...] = ()
    population: AnalysisPopulation | None = None


class Analyzer(Protocol):
    analysis_type: AnalysisType

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult: ...
