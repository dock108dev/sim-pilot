"""Provider-independent analysis-question compilation and deterministic fallback."""

from __future__ import annotations

from collections import deque
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sim_pilot.analysis.catalog import validate_analysis_request
from sim_pilot.analysis.contracts import (
    AnalysisFilter,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisRequest,
    AnalysisType,
    RankingDirection,
    RankingMetric,
    RankingRequest,
)


class AnalysisCompilation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request: AnalysisRequest | None = None
    clarification: str | None = Field(default=None, min_length=1)
    unsupported_reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def exactly_one_outcome(self) -> AnalysisCompilation:
        if (
            sum(
                item is not None
                for item in (self.request, self.clarification, self.unsupported_reason)
            )
            != 1
        ):
            raise ValueError("compilation must contain exactly one outcome")
        return self


class AnalysisCompiler(Protocol):
    async def compile(self, question: str) -> AnalysisCompilation: ...


class ScriptedAnalysisCompiler:
    def __init__(self, results: tuple[AnalysisCompilation, ...]) -> None:
        self._results = deque(results)

    async def compile(self, question: str) -> AnalysisCompilation:
        if not question.strip():
            raise ValueError("question must not be empty")
        if not self._results:
            raise RuntimeError("scripted analysis compiler exhausted")
        return self._results.popleft()


class DeterministicAnalysisCompiler:
    """Compile a bounded set of common questions without invoking a model."""

    async def compile(self, question: str) -> AnalysisCompilation:
        normalized = " ".join(question.lower().split())
        if not normalized:
            raise ValueError("question must not be empty")
        if any(term in normalized for term in ("ten years", "will be profitable", "future profit")):
            return AnalysisCompilation(
                unsupported_reason=(
                    "Future profit prediction requires a forecasting model and additional evidence."
                )
            )
        if "crash" in normalized and "why" in normalized:
            return AnalysisCompilation(
                unsupported_reason="Crash causality is not present in the canonical world snapshot."
            )
        if any(term in normalized for term in ("fix ", "build ", "buy ", "change orders")):
            return AnalysisCompilation(
                unsupported_reason=(
                    "Phase 8B analysis is read-only and cannot perform gameplay actions."
                )
            )
        if "which route is bad" in normalized or normalized == "which route is weak?":
            return AnalysisCompilation(
                clarification="Name a route or ask for a ranked review of all observed routes."
            )
        if normalized.rstrip("?") in {"what should i do", "is this okay"}:
            return AnalysisCompilation(
                clarification=(
                    "Ask about company health, vehicles, stations, routes, coverage, or changes."
                )
            )
        if "compare" in normalized and "before" in normalized:
            return AnalysisCompilation(
                clarification="Supply an explicit compatible comparison snapshot."
            )
        analysis_type = _analysis_type(normalized)
        if analysis_type is None:
            return AnalysisCompilation(
                unsupported_reason=(
                    "The question does not map to the supported deterministic analysis catalog."
                )
            )
        if analysis_type is AnalysisType.ANOMALY_DETECTION:
            return AnalysisCompilation(
                clarification=(
                    "Supply an explicit compatible comparison snapshot for anomaly review."
                )
            )
        filters: tuple[AnalysisFilter, ...] = ()
        vehicle_type = next(
            (
                canonical
                for word, canonical in (
                    ("train", "rail"),
                    ("rail", "rail"),
                    ("road", "road"),
                    ("truck", "road"),
                    ("bus", "road"),
                    ("ship", "water"),
                    ("aircraft", "air"),
                    ("plane", "air"),
                )
                if word in normalized
            ),
            None,
        )
        if vehicle_type is not None and analysis_type is AnalysisType.VEHICLE_PERFORMANCE:
            filters = (
                AnalysisFilter(
                    field=AnalysisFilterField.VEHICLE_TYPE,
                    operator=AnalysisFilterOperator.EQUAL,
                    values=(vehicle_type,),
                ),
            )
        ranking = _ranking(normalized, analysis_type)
        request = AnalysisRequest(
            analysis_type=analysis_type,
            question=question.strip(),
            filters=filters,
            ranking=ranking,
        )
        validate_analysis_request(request)
        return AnalysisCompilation(request=request)


def _analysis_type(question: str) -> AnalysisType | None:
    rules = (
        (("changed", "what changed"), AnalysisType.WORLD_CHANGES),
        (("unusual", "anomal"), AnalysisType.ANOMALY_DETECTION),
        (("pay attention", "inspect first", "what next", "priority"), AnalysisType.PRIORITY_REVIEW),
        (("station", "waiting cargo", "capacity"), AnalysisType.STATION_PERFORMANCE),
        (("route",), AnalysisType.ROUTE_PERFORMANCE),
        (("industry",), AnalysisType.INDUSTRY_OPPORTUNITIES),
        (("town",), AnalysisType.TOWN_COVERAGE),
        (
            ("coverage", "cargo types are missing", "service opportunity"),
            AnalysisType.SERVICE_COVERAGE,
        ),
        (
            ("vehicle", "train", "truck", "bus", "ship", "aircraft", "plane"),
            AnalysisType.VEHICLE_PERFORMANCE,
        ),
        (("fleet", "concentrated"), AnalysisType.FLEET_SUMMARY),
        (
            ("debt", "cash position", "financial summary", "finances"),
            AnalysisType.FINANCIAL_SUMMARY,
        ),
        (("losing money", "company health", "healthy is", "health"), AnalysisType.COMPANY_HEALTH),
    )
    for terms, analysis_type in rules:
        if any(term in question for term in terms):
            return analysis_type
    return None


def _ranking(question: str, analysis_type: AnalysisType) -> RankingRequest | None:
    if analysis_type is AnalysisType.VEHICLE_PERFORMANCE:
        if any(term in question for term in ("least", "losing", "worst", "underperform")):
            return RankingRequest(
                metric=RankingMetric.PROFIT_LAST_YEAR,
                direction=RankingDirection.ASCENDING,
            )
        if any(term in question for term in ("best", "most profitable")):
            return RankingRequest(
                metric=RankingMetric.PROFIT_LAST_YEAR,
                direction=RankingDirection.DESCENDING,
            )
    if analysis_type is AnalysisType.STATION_PERFORMANCE and "most" in question:
        return RankingRequest(
            metric=RankingMetric.WAITING_CARGO,
            direction=RankingDirection.DESCENDING,
        )
    if analysis_type is AnalysisType.ROUTE_PERFORMANCE:
        if any(term in question for term in ("worst", "losing", "least", "bad")):
            return RankingRequest(
                metric=RankingMetric.ROUTE_AGGREGATE_PROFIT,
                direction=RankingDirection.ASCENDING,
            )
        if any(term in question for term in ("best", "most money", "most profitable")):
            return RankingRequest(
                metric=RankingMetric.ROUTE_AGGREGATE_PROFIT,
                direction=RankingDirection.DESCENDING,
            )
    return None
