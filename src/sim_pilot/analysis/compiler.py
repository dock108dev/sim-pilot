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
    AnalysisSubjectType,
    AnalysisType,
    AnswerConcept,
    AnswerIntent,
    AnswerKind,
    AnswerMetric,
    AnswerPeriod,
    ConversationReferenceKind,
    EvidenceRequirement,
    EvidenceRequirementKind,
    PremiseType,
    QuestionForm,
    RankingDirection,
    RankingMetric,
    RankingRequest,
    ResolvedConversationReference,
)
from sim_pilot.analysis.errors import AnalysisRequestError


def _empty_entity_counts() -> dict[AnalysisSubjectType, int]:
    return {}


class AnalysisEntityContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    subject_type: AnalysisSubjectType
    canonical_id: str = Field(min_length=1)
    alias: str = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1)


class AnalysisFindingContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    finding_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    entity_ids: tuple[str, ...] = Field(max_length=10)


class AnalysisCompilerContext(BaseModel):
    """Bounded context for comparison and follow-up reference resolution."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    comparison_snapshot_id: str | None = Field(default=None, min_length=1)
    prior_analysis_id: str | None = Field(default=None, pattern=r"^analysis:[0-9a-f]{20}$")
    entity_counts: dict[AnalysisSubjectType, int] = Field(default_factory=_empty_entity_counts)
    focus_entities: tuple[AnalysisEntityContext, ...] = Field(default=(), max_length=10)
    prior_findings: tuple[AnalysisFindingContext, ...] = Field(default=(), max_length=5)


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
    async def compile(
        self,
        question: str,
        *,
        context: AnalysisCompilerContext | None = None,
    ) -> AnalysisCompilation: ...


class ScriptedAnalysisCompiler:
    def __init__(self, results: tuple[AnalysisCompilation, ...]) -> None:
        self._results = deque(results)

    async def compile(
        self,
        question: str,
        *,
        context: AnalysisCompilerContext | None = None,
    ) -> AnalysisCompilation:
        del context
        if not question.strip():
            raise ValueError("question must not be empty")
        if not self._results:
            raise RuntimeError("scripted analysis compiler exhausted")
        return self._results.popleft()


class DeterministicAnalysisCompiler:
    """Compile a bounded set of common questions without invoking a model."""

    async def compile(
        self,
        question: str,
        *,
        context: AnalysisCompilerContext | None = None,
    ) -> AnalysisCompilation:
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
        reference_kind, reference_phrase = _conversation_reference(normalized)
        resolved_entity: AnalysisEntityContext | None = None
        resolved_finding: AnalysisFindingContext | None = None
        if reference_kind is not None:
            if context is None:
                return AnalysisCompilation(clarification=_reference_clarification(reference_kind))
            if reference_kind is ConversationReferenceKind.FINDING:
                if len(context.prior_findings) != 1:
                    return AnalysisCompilation(clarification="Which displayed finding do you mean?")
                resolved_finding = context.prior_findings[0]
                candidates = tuple(
                    item
                    for item in context.focus_entities
                    if item.canonical_id in resolved_finding.entity_ids
                )
            else:
                subject = _reference_subject(reference_kind)
                candidates = tuple(
                    item
                    for item in context.focus_entities
                    if subject is None or item.subject_type is subject
                )
            if len(candidates) != 1:
                return AnalysisCompilation(clarification=_reference_clarification(reference_kind))
            resolved_entity = candidates[0]
        analysis_type = _analysis_type(normalized)
        if analysis_type is None and resolved_entity is not None:
            analysis_type = AnalysisType.ENTITY_SUMMARY
        if analysis_type is None:
            return AnalysisCompilation(
                unsupported_reason=(
                    "The question does not map to the supported deterministic analysis catalog."
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
        subject_type = _subject_scope(normalized, analysis_type)
        subject_ids: tuple[str, ...] = ()
        resolved_reference = None
        if resolved_entity is not None:
            assert reference_kind is not None
            subject_type = resolved_entity.subject_type
            subject_ids = (resolved_entity.canonical_id,)
            if context is not None and context.prior_analysis_id is not None:
                resolved_reference = ResolvedConversationReference(
                    kind=reference_kind,
                    phrase=reference_phrase,
                    prior_analysis_id=context.prior_analysis_id,
                    subject_type=resolved_entity.subject_type,
                    entity_id=resolved_entity.canonical_id,
                    finding_id=(None if resolved_finding is None else resolved_finding.finding_id),
                )
        request = AnalysisRequest(
            analysis_type=analysis_type,
            question=question.strip(),
            subject_type=subject_type,
            subject_ids=subject_ids,
            filters=filters,
            ranking=ranking,
            comparison_snapshot_id=(None if context is None else context.comparison_snapshot_id),
            answer_intent=answer_intent_for_question(
                normalized, analysis_type, ranking, subject_type
            ),
            resolved_reference=resolved_reference,
        )
        validate_analysis_request(request)
        return AnalysisCompilation(request=request)


def _analysis_type(question: str) -> AnalysisType | None:
    if "vehicle type" in question and any(
        term in question for term in ("dragging", "loses", "loss", "least profitable")
    ):
        return AnalysisType.FLEET_SUMMARY
    rules = (
        (
            (
                "changed",
                "what changed",
                "improving",
                "getting worse",
                "gained",
                "became unprofitable",
                "become unprofitable",
            ),
            AnalysisType.WORLD_CHANGES,
        ),
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
            ("debt", "cash", "financial summary", "finances"),
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
        if "losing vehicles" in question:
            return RankingRequest(
                metric=RankingMetric.ROUTE_NEGATIVE_VEHICLE_COUNT,
                direction=RankingDirection.DESCENDING,
            )
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
    if analysis_type is AnalysisType.FLEET_SUMMARY and "vehicle type" in question:
        return RankingRequest(
            metric=RankingMetric.VEHICLE_TYPE_AGGREGATE_PROFIT,
            direction=RankingDirection.ASCENDING,
        )
    if analysis_type is AnalysisType.PRIORITY_REVIEW:
        return RankingRequest(
            metric=RankingMetric.PRIORITY_SCORE,
            direction=RankingDirection.DESCENDING,
        )
    return None


def _subject_scope(question: str, analysis_type: AnalysisType) -> AnalysisSubjectType | None:
    if analysis_type is AnalysisType.WORLD_CHANGES:
        for terms, subject in (
            (
                ("vehicle", "train", "truck", "bus", "ship", "aircraft"),
                AnalysisSubjectType.VEHICLE,
            ),
            (("town",), AnalysisSubjectType.TOWN),
            (("station",), AnalysisSubjectType.STATION),
            (("route",), AnalysisSubjectType.ROUTE),
            (("industry",), AnalysisSubjectType.INDUSTRY),
            (("company",), AnalysisSubjectType.COMPANY),
        ):
            if any(term in question for term in terms):
                return subject
    if analysis_type is AnalysisType.PRIORITY_REVIEW:
        for terms, subject in (
            (("station",), AnalysisSubjectType.STATION),
            (("vehicle", "train", "truck", "bus", "ship", "aircraft"), AnalysisSubjectType.VEHICLE),
            (("route",), AnalysisSubjectType.ROUTE),
            (("industry",), AnalysisSubjectType.INDUSTRY),
            (("town",), AnalysisSubjectType.TOWN),
        ):
            if any(term in question for term in terms):
                return subject
    if analysis_type is AnalysisType.FLEET_SUMMARY and "vehicle type" in question:
        return AnalysisSubjectType.VEHICLE
    return None


def _conversation_reference(
    question: str,
) -> tuple[ConversationReferenceKind | None, str]:
    for phrase, kind in (
        ("that vehicle", ConversationReferenceKind.VEHICLE),
        ("this vehicle", ConversationReferenceKind.VEHICLE),
        ("that route", ConversationReferenceKind.ROUTE),
        ("this route", ConversationReferenceKind.ROUTE),
        ("that station", ConversationReferenceKind.STATION),
        ("this station", ConversationReferenceKind.STATION),
        ("that finding", ConversationReferenceKind.FINDING),
        ("this finding", ConversationReferenceKind.FINDING),
        ("the top opportunity", ConversationReferenceKind.TOP_OPPORTUNITY),
    ):
        if phrase in question:
            return kind, phrase
    return None, ""


def _reference_subject(
    kind: ConversationReferenceKind,
) -> AnalysisSubjectType | None:
    return {
        ConversationReferenceKind.VEHICLE: AnalysisSubjectType.VEHICLE,
        ConversationReferenceKind.ROUTE: AnalysisSubjectType.ROUTE,
        ConversationReferenceKind.STATION: AnalysisSubjectType.STATION,
    }.get(kind)


def _reference_clarification(kind: ConversationReferenceKind) -> str:
    label = kind.value.replace("_", " ")
    return f"Which {label} do you mean? Name one or continue from one displayed result."


def answer_intent_for_question(
    question: str,
    analysis_type: AnalysisType,
    ranking: RankingRequest | None,
    subject_type: AnalysisSubjectType | None = None,
) -> AnswerIntent:
    comparison_required = any(
        term in question
        for term in ("changed", "change", "since", "before", "improving", "worse", "unusual")
    )
    if analysis_type is AnalysisType.COMPANY_HEALTH:
        if "losing money" in question or "loss" in question:
            return AnswerIntent(
                concept=AnswerConcept.LOSS,
                kind=AnswerKind.EXPLANATION,
                question_forms=(QuestionForm.PREMISE_CHECK, QuestionForm.CAUSE),
                requested_metric=AnswerMetric.NET_OPERATING_RESULT,
                period=AnswerPeriod.CURRENT,
                premise=PremiseType.COMPANY_LOSING,
                premise_asserted=True,
                evidence_requirements=_evidence_requirements(
                    (QuestionForm.PREMISE_CHECK, QuestionForm.CAUSE),
                    AnswerMetric.NET_OPERATING_RESULT,
                    AnalysisSubjectType.COMPANY,
                ),
            )
        return AnswerIntent(
            concept=AnswerConcept.HEALTH,
            kind=AnswerKind.FACT,
            question_forms=(QuestionForm.STATUS, QuestionForm.SUMMARY),
            requested_metric=AnswerMetric.NET_OPERATING_RESULT,
            period=AnswerPeriod.CURRENT,
            evidence_requirements=_evidence_requirements(
                (QuestionForm.STATUS, QuestionForm.SUMMARY),
                AnswerMetric.NET_OPERATING_RESULT,
                AnalysisSubjectType.COMPANY,
            ),
        )
    if analysis_type is AnalysisType.FINANCIAL_SUMMARY:
        if "debt" in question or "loan" in question:
            return AnswerIntent(
                concept=AnswerConcept.DEBT,
                kind=AnswerKind.FACT,
                question_forms=(
                    (QuestionForm.QUANTITY,) if "how much" in question else (QuestionForm.STATUS,)
                ),
                requested_metric=AnswerMetric.LOAN,
                period=AnswerPeriod.CURRENT,
                premise_asserted="too much" in question,
                evidence_requirements=_evidence_requirements(
                    (QuestionForm.STATUS,),
                    AnswerMetric.LOAN,
                    AnalysisSubjectType.COMPANY,
                ),
            )
        if "cash" in question:
            return AnswerIntent(
                concept=AnswerConcept.AVAILABLE_CASH,
                kind=AnswerKind.FACT,
                question_forms=(QuestionForm.QUANTITY,),
                requested_metric=AnswerMetric.CASH,
                period=AnswerPeriod.CURRENT,
                evidence_requirements=_evidence_requirements(
                    (QuestionForm.QUANTITY,),
                    AnswerMetric.CASH,
                    AnalysisSubjectType.COMPANY,
                ),
            )
    if analysis_type in {AnalysisType.WORLD_CHANGES, AnalysisType.ANOMALY_DETECTION}:
        metric = None
        if "population" in question or "town" in question:
            metric = AnswerMetric.POPULATION
        elif "profit" in question or "unprofitable" in question:
            metric = AnswerMetric.PROFIT_LAST_YEAR
        return AnswerIntent(
            concept=(
                AnswerConcept.ANOMALY
                if analysis_type is AnalysisType.ANOMALY_DETECTION
                else AnswerConcept.CHANGE
            ),
            kind=AnswerKind.RANKING,
            question_forms=(QuestionForm.COMPARISON,),
            requested_metric=metric,
            period=AnswerPeriod.BETWEEN_SNAPSHOTS,
            comparison_required=True,
            evidence_requirements=_evidence_requirements(
                (QuestionForm.COMPARISON,),
                metric,
                subject_type or AnalysisSubjectType.WORLD,
            ),
        )
    if analysis_type is AnalysisType.VEHICLE_PERFORMANCE:
        vehicle_reference = any(term in question for term in ("this vehicle", "that vehicle"))
        if "flag" in question and vehicle_reference:
            return AnswerIntent(
                concept=AnswerConcept.ENTITY,
                kind=AnswerKind.ENTITY_FOLLOW_UP,
                question_forms=(QuestionForm.DRILL_DOWN, QuestionForm.EVIDENCE),
                period=AnswerPeriod.CURRENT_SNAPSHOT,
                reference_kind=ConversationReferenceKind.VEHICLE,
                evidence_requirements=_evidence_requirements(
                    (QuestionForm.DRILL_DOWN, QuestionForm.EVIDENCE),
                    None,
                    AnalysisSubjectType.VEHICLE,
                ),
            )
        if "idle" in question or "sitting" in question:
            return AnswerIntent(
                concept=AnswerConcept.IDLE,
                kind=AnswerKind.FACT,
                question_forms=(QuestionForm.EXISTENCE,),
                requested_metric=AnswerMetric.RUNNING_STATE,
                period=AnswerPeriod.CURRENT_SNAPSHOT,
                evidence_requirements=_evidence_requirements(
                    (QuestionForm.EXISTENCE,),
                    AnswerMetric.RUNNING_STATE,
                    AnalysisSubjectType.VEHICLE,
                ),
            )
        metric = _answer_metric(ranking)
        forms = (QuestionForm.RANKING,) if ranking is not None else (QuestionForm.SUMMARY,)
        return AnswerIntent(
            concept=AnswerConcept.PERFORMANCE,
            kind=AnswerKind.RANKING if ranking is not None else AnswerKind.FACT,
            question_forms=forms,
            requested_metric=metric,
            period=_period(metric),
            comparison_required=comparison_required,
            evidence_requirements=_evidence_requirements(
                forms, metric, subject_type or AnalysisSubjectType.VEHICLE
            ),
        )
    if analysis_type is AnalysisType.ROUTE_PERFORMANCE:
        metric = _answer_metric(ranking)
        reference = (
            ConversationReferenceKind.ROUTE
            if any(term in question for term in ("this route", "that route"))
            else None
        )
        premise = PremiseType.ROUTE_LOSING if "losing money" in question else None
        forms = (
            (QuestionForm.PREMISE_CHECK, QuestionForm.CAUSE, QuestionForm.DRILL_DOWN)
            if premise is not None
            else (
                (QuestionForm.DRILL_DOWN, QuestionForm.EVIDENCE)
                if "contribute" in question and reference is not None
                else (QuestionForm.RANKING,)
            )
        )
        return AnswerIntent(
            concept=AnswerConcept.PERFORMANCE,
            kind=AnswerKind.ENTITY_FOLLOW_UP if "this route" in question else AnswerKind.RANKING,
            question_forms=forms,
            requested_metric=metric,
            period=AnswerPeriod.LAST_YEAR,
            premise=premise,
            premise_asserted=premise is not None,
            comparison_required=comparison_required,
            reference_kind=reference,
            evidence_requirements=_evidence_requirements(
                forms, metric or AnswerMetric.ROUTE_AGGREGATE_PROFIT, AnalysisSubjectType.ROUTE
            ),
        )
    if analysis_type is AnalysisType.FLEET_SUMMARY and "vehicle type" in question:
        return AnswerIntent(
            concept=AnswerConcept.PERFORMANCE,
            kind=AnswerKind.RANKING,
            question_forms=(QuestionForm.RANKING,),
            requested_metric=AnswerMetric.VEHICLE_TYPE_AGGREGATE_PROFIT,
            period=AnswerPeriod.LAST_YEAR,
            evidence_requirements=_evidence_requirements(
                (QuestionForm.RANKING,),
                AnswerMetric.VEHICLE_TYPE_AGGREGATE_PROFIT,
                AnalysisSubjectType.VEHICLE,
            ),
        )
    concepts = {
        AnalysisType.STATION_PERFORMANCE: AnswerConcept.PRIORITY,
        AnalysisType.SERVICE_COVERAGE: AnswerConcept.COVERAGE,
        AnalysisType.INDUSTRY_OPPORTUNITIES: AnswerConcept.OPPORTUNITY,
        AnalysisType.TOWN_COVERAGE: AnswerConcept.COVERAGE,
        AnalysisType.PRIORITY_REVIEW: AnswerConcept.PRIORITY,
        AnalysisType.ENTITY_SUMMARY: AnswerConcept.ENTITY,
    }
    metric = _answer_metric(ranking)
    if analysis_type is AnalysisType.SERVICE_COVERAGE and "cargo type" in question:
        metric = AnswerMetric.CARGO_TYPE_COVERAGE
    station_reference = analysis_type is AnalysisType.STATION_PERFORMANCE and any(
        term in question for term in ("this station", "that station")
    )
    if station_reference and any(term in question for term in ("why", "what makes")):
        forms = (QuestionForm.DRILL_DOWN, QuestionForm.EVIDENCE, QuestionForm.CAUSE)
    elif analysis_type is AnalysisType.PRIORITY_REVIEW:
        forms = (QuestionForm.RECOMMENDATION, QuestionForm.RANKING)
    else:
        forms = (QuestionForm.RANKING,) if ranking is not None else (QuestionForm.SUMMARY,)
    return AnswerIntent(
        concept=concepts.get(analysis_type, AnswerConcept.PERFORMANCE),
        kind=(
            AnswerKind.ENTITY_FOLLOW_UP
            if station_reference
            else AnswerKind.RANKING
            if ranking is not None
            else AnswerKind.FACT
        ),
        question_forms=forms,
        requested_metric=metric,
        period=_period(metric),
        comparison_required=comparison_required,
        reference_kind=(ConversationReferenceKind.STATION if station_reference else None),
        evidence_requirements=_evidence_requirements(forms, metric, subject_type),
    )


def normalize_provider_compilation(compilation: AnalysisCompilation) -> AnalysisCompilation:
    """Validate provider semantics and fill only a missing deterministic answer intent."""
    request = compilation.request
    if request is None:
        return compilation
    normalized = " ".join(request.question.casefold().split())
    inferred = answer_intent_for_question(
        normalized, request.analysis_type, request.ranking, request.subject_type
    )
    if request.answer_intent is None:
        request = request.model_copy(update={"answer_intent": inferred})
    else:
        supplied = request.answer_intent
        if (
            supplied.concept is not inferred.concept
            or supplied.kind is not inferred.kind
            or set(supplied.question_forms) != set(inferred.question_forms)
            or supplied.requested_metric is not inferred.requested_metric
            or supplied.period is not inferred.period
            or supplied.premise is not inferred.premise
            or supplied.comparison_required is not inferred.comparison_required
            or supplied.reference_kind is not inferred.reference_kind
        ):
            raise AnalysisRequestError(
                "provider answer intent does not match the normalized question"
            )
        request = request.model_copy(update={"answer_intent": inferred})
    expected_type = _required_analysis_type(normalized)
    if expected_type is not None and request.analysis_type is not expected_type:
        raise AnalysisRequestError(
            f"provider selected {request.analysis_type.value} for a question requiring "
            f"{expected_type.value}"
        )
    validate_analysis_request(request)
    return compilation.model_copy(update={"request": request})


def _required_analysis_type(question: str) -> AnalysisType | None:
    if "losing money" in question:
        return AnalysisType.COMPANY_HEALTH
    if "debt" in question or "cash" in question:
        return AnalysisType.FINANCIAL_SUMMARY
    if "improving" in question or "getting worse" in question:
        return AnalysisType.WORLD_CHANGES
    return None


def _answer_metric(ranking: RankingRequest | None) -> AnswerMetric | None:
    if ranking is None:
        return None
    return ranking.metric


def _period(metric: AnswerMetric | None) -> AnswerPeriod | None:
    if metric is AnswerMetric.PROFIT_LAST_YEAR:
        return AnswerPeriod.LAST_YEAR
    if metric is AnswerMetric.PROFIT_THIS_YEAR:
        return AnswerPeriod.THIS_YEAR
    if metric in {
        AnswerMetric.VEHICLE_TYPE_AGGREGATE_PROFIT,
        AnswerMetric.ROUTE_AGGREGATE_PROFIT,
        AnswerMetric.ROUTE_MEDIAN_PROFIT,
        AnswerMetric.ROUTE_NEGATIVE_VEHICLE_COUNT,
    }:
        return AnswerPeriod.LAST_YEAR
    return AnswerPeriod.CURRENT_SNAPSHOT if metric is not None else None


def _evidence_requirements(
    forms: tuple[QuestionForm, ...],
    metric: RankingMetric | None,
    subject_type: AnalysisSubjectType | None,
) -> tuple[EvidenceRequirement, ...]:
    values = [EvidenceRequirement(kind=EvidenceRequirementKind.CURRENT_SNAPSHOT)]
    if QuestionForm.COMPARISON in forms:
        values.extend(
            (
                EvidenceRequirement(kind=EvidenceRequirementKind.COMPARISON_SNAPSHOT),
                EvidenceRequirement(kind=EvidenceRequirementKind.COMPATIBLE_IDENTITY),
            )
        )
        if metric is not None:
            values.append(
                EvidenceRequirement(
                    kind=EvidenceRequirementKind.METRIC_BOTH_SNAPSHOTS,
                    metric=metric,
                    subject_type=subject_type,
                )
            )
    elif metric is not None:
        values.append(
            EvidenceRequirement(
                kind=EvidenceRequirementKind.METRIC_CURRENT,
                metric=metric,
                subject_type=subject_type,
            )
        )
    if QuestionForm.RANKING in forms:
        values.append(
            EvidenceRequirement(
                kind=EvidenceRequirementKind.ELIGIBLE_POPULATION,
                metric=metric,
                subject_type=subject_type,
            )
        )
    if QuestionForm.CAUSE in forms:
        values.append(
            EvidenceRequirement(
                kind=EvidenceRequirementKind.CANDIDATE_CONTRIBUTORS,
                metric=metric,
                subject_type=subject_type,
            )
        )
    if QuestionForm.DRILL_DOWN in forms:
        values.append(
            EvidenceRequirement(
                kind=EvidenceRequirementKind.RESOLVED_SUBJECT,
                subject_type=subject_type,
            )
        )
    return tuple(values)
