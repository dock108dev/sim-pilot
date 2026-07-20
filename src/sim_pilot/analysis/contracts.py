"""Immutable public contracts for read-only gameplay analysis."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from sim_pilot.domain.models import JsonValue


class AnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class AnalysisType(StrEnum):
    COMPANY_HEALTH = "company_health"
    FINANCIAL_SUMMARY = "financial_summary"
    VEHICLE_PERFORMANCE = "vehicle_performance"
    STATION_PERFORMANCE = "station_performance"
    ROUTE_PERFORMANCE = "route_performance"
    SERVICE_COVERAGE = "service_coverage"
    INDUSTRY_OPPORTUNITIES = "industry_opportunities"
    TOWN_COVERAGE = "town_coverage"
    FLEET_SUMMARY = "fleet_summary"
    WORLD_CHANGES = "world_changes"
    ANOMALY_DETECTION = "anomaly_detection"
    PRIORITY_REVIEW = "priority_review"
    ENTITY_SUMMARY = "entity_summary"


class AnalysisSubjectType(StrEnum):
    WORLD = "world"
    COMPANY = "company"
    TOWN = "town"
    INDUSTRY = "industry"
    STATION = "station"
    VEHICLE = "vehicle"
    ROUTE = "route"


class AnalysisFilterField(StrEnum):
    ENTITY_ID = "entity_id"
    OWNER_ID = "owner_id"
    VEHICLE_TYPE = "vehicle_type"
    ROUTE_ID = "route_id"
    RUNNING_STATE = "running_state"
    IN_DEPOT = "in_depot"
    PROFIT_THIS_YEAR = "profit_this_year"
    PROFIT_LAST_YEAR = "profit_last_year"
    AGE_DAYS = "age_days"
    STATION_ID = "station_id"
    TOWN_ID = "town_id"
    INDUSTRY_ID = "industry_id"


class AnalysisFilterOperator(StrEnum):
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    IN = "in"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"


type AnalysisScalar = str | int | bool


class AnalysisFilter(AnalysisModel):
    field: AnalysisFilterField
    operator: AnalysisFilterOperator
    values: tuple[AnalysisScalar, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_arity(self) -> Self:
        if self.operator is not AnalysisFilterOperator.IN and len(self.values) != 1:
            raise ValueError(f"{self.operator.value} requires exactly one value")
        return self


class RankingDirection(StrEnum):
    ASCENDING = "ascending"
    DESCENDING = "descending"


class RankingMetric(StrEnum):
    """Canonical metric catalog shared by intent, ranking, evidence, and output."""

    CASH = "cash"
    LOAN = "loan"
    COMPANY_VALUE = "company_value"
    INCOME = "income"
    EXPENSES = "expenses"
    NET_OPERATING_RESULT = "net_operating_result"
    PROFIT_THIS_YEAR = "profit_this_year"
    PROFIT_LAST_YEAR = "profit_last_year"
    AGE_DAYS = "age_days"
    RUNNING_STATE = "running_state"
    WAITING_CARGO = "waiting_cargo"
    CARGO_PER_VEHICLE = "cargo_per_vehicle"
    CARGO_TYPE_COVERAGE = "cargo_type_coverage"
    VEHICLE_COUNT = "vehicle_count"
    NEGATIVE_PROFIT_VEHICLE_COUNT = "negative_profit_vehicle_count"
    VEHICLE_TYPE_AGGREGATE_PROFIT = "vehicle_type_aggregate_profit"
    ROUTE_AGGREGATE_PROFIT = "route_aggregate_profit"
    ROUTE_MEDIAN_PROFIT = "route_median_profit"
    ROUTE_NEGATIVE_VEHICLE_COUNT = "route_negative_vehicle_count"
    POPULATION = "population"
    PRODUCTION = "production"
    OPPORTUNITY_SCORE = "opportunity_score"
    PRIORITY_SCORE = "priority_score"
    MATERIALITY = "materiality"


class RankingRequest(AnalysisModel):
    metric: RankingMetric
    direction: RankingDirection
    limit: int = Field(default=1, ge=1, le=20)


class AnswerConcept(StrEnum):
    HEALTH = "health"
    LOSS = "loss"
    DEBT = "debt"
    AVAILABLE_CASH = "available_cash"
    CHANGE = "change"
    PERFORMANCE = "performance"
    IDLE = "idle"
    COVERAGE = "coverage"
    OPPORTUNITY = "opportunity"
    PRIORITY = "priority"
    ANOMALY = "anomaly"
    ENTITY = "entity"


class AnswerKind(StrEnum):
    FACT = "fact"
    RANKING = "ranking"
    EXPLANATION = "explanation"
    ENTITY_FOLLOW_UP = "entity_follow_up"


class QuestionForm(StrEnum):
    STATUS = "status"
    EXISTENCE = "existence"
    QUANTITY = "quantity"
    RANKING = "ranking"
    COMPARISON = "comparison"
    CAUSE = "cause"
    RECOMMENDATION = "recommendation"
    SUMMARY = "summary"
    EVIDENCE = "evidence"
    DRILL_DOWN = "drill_down"
    PREMISE_CHECK = "premise_check"


class AnswerPeriod(StrEnum):
    OBSERVED = "observed"
    CURRENT = "current"
    THIS_YEAR = "this_year"
    CURRENT_YEAR = "current_year"
    LAST_YEAR = "last_year"
    CURRENT_SNAPSHOT = "current_snapshot"
    PREVIOUS_SNAPSHOT = "previous_snapshot"
    BETWEEN_SNAPSHOTS = "between_snapshots"


AnswerMetric = RankingMetric


class PremiseType(StrEnum):
    COMPANY_LOSING = "company_losing"
    ROUTE_LOSING = "route_losing"
    STATION_CONGESTED = "station_congested"
    PERFORMANCE_WORSE = "performance_worse"


class ConversationReferenceKind(StrEnum):
    VEHICLE = "vehicle"
    ROUTE = "route"
    STATION = "station"
    FINDING = "finding"
    TOP_OPPORTUNITY = "top_opportunity"


class EvidenceRequirementKind(StrEnum):
    CURRENT_SNAPSHOT = "current_snapshot"
    COMPARISON_SNAPSHOT = "comparison_snapshot"
    COMPATIBLE_IDENTITY = "compatible_identity"
    METRIC_CURRENT = "metric_current"
    METRIC_BOTH_SNAPSHOTS = "metric_both_snapshots"
    ELIGIBLE_POPULATION = "eligible_population"
    RESOLVED_SUBJECT = "resolved_subject"
    CANDIDATE_CONTRIBUTORS = "candidate_contributors"


class EvidenceRequirement(AnalysisModel):
    kind: EvidenceRequirementKind
    metric: RankingMetric | None = None
    subject_type: AnalysisSubjectType | None = None


class ResolvedConversationReference(AnalysisModel):
    kind: ConversationReferenceKind
    phrase: str = Field(min_length=1, max_length=100)
    prior_analysis_id: str = Field(pattern=r"^analysis:[0-9a-f]{20}$")
    subject_type: AnalysisSubjectType | None = None
    entity_id: str | None = Field(default=None, min_length=1)
    finding_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.entity_id is None and self.finding_id is None:
            raise ValueError("a resolved conversational reference requires a target")
        if self.entity_id is not None and self.subject_type is None:
            raise ValueError("an entity reference requires subject_type")
        return self


class AnswerIntent(AnalysisModel):
    """Question semantics used only to shape an evidence-backed answer."""

    concept: AnswerConcept
    kind: AnswerKind
    question_forms: tuple[QuestionForm, ...] = Field(default=(), max_length=4)
    requested_metric: RankingMetric | None = None
    period: AnswerPeriod | None = None
    premise: PremiseType | None = None
    premise_asserted: bool = False
    comparison_required: bool = False
    reference_kind: ConversationReferenceKind | None = None
    evidence_requirements: tuple[EvidenceRequirement, ...] = Field(default=(), max_length=10)

    @model_validator(mode="after")
    def validate_semantics(self) -> Self:
        if len(set(self.question_forms)) != len(self.question_forms):
            raise ValueError("question forms must be unique")
        if self.premise is not None and QuestionForm.PREMISE_CHECK not in self.question_forms:
            raise ValueError("a premise requires premise_check question form")
        return self


class AnalysisRequest(AnalysisModel):
    adapter_type: Literal["openttd"] = "openttd"
    analysis_type: AnalysisType
    question: str = Field(min_length=1, max_length=2_000)
    subject_type: AnalysisSubjectType | None = None
    subject_ids: tuple[str, ...] = Field(default=(), max_length=100)
    filters: tuple[AnalysisFilter, ...] = Field(default=(), max_length=20)
    ranking: RankingRequest | None = None
    comparison_snapshot_id: str | None = Field(default=None, min_length=1)
    maximum_findings: int = Field(default=5, ge=1, le=20)
    include_recommendations: bool = True
    answer_intent: AnswerIntent | None = None
    resolved_reference: ResolvedConversationReference | None = None

    @model_validator(mode="after")
    def validate_subject(self) -> Self:
        if self.subject_ids and self.subject_type is None:
            raise ValueError("subject_ids require subject_type")
        if self.analysis_type is AnalysisType.ENTITY_SUMMARY and not self.subject_ids:
            raise ValueError("entity_summary requires subject IDs")
        if len(set(self.subject_ids)) != len(self.subject_ids):
            raise ValueError("subject_ids must be unique")
        return self


class EvidenceSourceType(StrEnum):
    SNAPSHOT_FIELD = "snapshot_field"
    DERIVED_METRIC = "derived_metric"
    SNAPSHOT_CHANGE = "snapshot_change"
    CAPABILITY_COVERAGE = "capability_coverage"


class EvidenceReference(AnalysisModel):
    source_type: EvidenceSourceType
    snapshot_id: str = Field(min_length=1)
    entity_type: AnalysisSubjectType | None = None
    entity_id: str | None = Field(default=None, min_length=1)
    field: str = Field(min_length=1)
    observed_value: JsonValue
    comparison_snapshot_id: str | None = Field(default=None, min_length=1)
    comparison_value: JsonValue = None
    metric_inputs: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_entity_and_comparison(self) -> Self:
        if (self.entity_type is None) != (self.entity_id is None):
            raise ValueError("entity_type and entity_id must be supplied together")
        if self.comparison_value is not None and self.comparison_snapshot_id is None:
            raise ValueError("comparison_value requires comparison_snapshot_id")
        return self


class FindingKind(StrEnum):
    OBSERVED_FACT = "observed_fact"
    INFERRED_FINDING = "inferred_finding"
    DATA_QUALITY = "data_quality"


class FindingSeverity(StrEnum):
    INFORMATIONAL = "informational"
    OPPORTUNITY = "opportunity"
    WARNING = "warning"
    CRITICAL = "critical"


class EvidenceConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AnalysisFinding(AnalysisModel):
    finding_id: str = Field(min_length=1)
    finding_code: str = Field(min_length=1)
    analysis_type: AnalysisType
    kind: FindingKind
    severity: FindingSeverity
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    metric_name: str | None = Field(default=None, min_length=1)
    metric_value: JsonValue = None
    comparison_value: JsonValue = None
    confidence: EvidenceConfidence
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=20)
    limitations: tuple[str, ...] = ()
    recommendation_ids: tuple[str, ...] = ()


class AnalysisRecommendation(AnalysisModel):
    recommendation_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    priority: int = Field(ge=1, le=100)
    affected_entity_ids: tuple[str, ...] = ()
    supporting_finding_ids: tuple[str, ...] = Field(min_length=1)
    required_capabilities: tuple[str, ...] = ()
    executable: Literal[False] = False
    limitations: tuple[str, ...] = ()


class ExplanationClaimType(StrEnum):
    SUMMARY = "summary"
    POSSIBLE_CONTRIBUTOR = "possible_contributor"
    RECOMMENDATION = "recommendation"
    LIMITATION = "limitation"


class ExplanationMetricReference(AnalysisModel):
    finding_id: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    metric_value: JsonValue


class AnalysisExplanationStatement(AnalysisModel):
    claim_type: ExplanationClaimType
    text: str = Field(min_length=1, max_length=2_000)
    finding_ids: tuple[str, ...] = ()
    recommendation_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    metric_references: tuple[ExplanationMetricReference, ...] = ()


class AnalysisExplanation(AnalysisModel):
    statements: tuple[AnalysisExplanationStatement, ...] = Field(min_length=1, max_length=20)


class AnalysisStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_LIMITATIONS = "completed_with_limitations"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT_DATA = "insufficient_data"
    FAILED = "failed"


class ExplanationValue(StrEnum):
    NOT_INVOKED = "not_invoked"
    IMPROVED_ANSWER = "improved_answer"
    NEUTRAL = "neutral"
    MADE_ANSWER_WORSE = "made_answer_worse"
    REJECTED_BY_VALIDATOR = "rejected_by_validator"
    PROVIDER_FAILED = "provider_failed"


class AnswerBasis(StrEnum):
    CONFIRMED_FACT = "confirmed_fact"
    FINDING = "finding"
    INFERENCE = "inference"
    INSUFFICIENT_DATA = "insufficient_data"


class AnalysisPresentation(AnalysisModel):
    """Deterministic compact-answer selection over authoritative analysis output."""

    direct_answer: str = Field(min_length=1)
    basis: AnswerBasis
    decisive_finding_id: str | None = Field(default=None, min_length=1)
    recommendation_id: str | None = Field(default=None, min_length=1)
    limitation: str | None = Field(default=None, min_length=1)
    follow_up: str | None = Field(default=None, min_length=1)
    evaluated_count: int | None = Field(default=None, ge=0)
    excluded_count: int | None = Field(default=None, ge=0)


class AnalysisPopulation(AnalysisModel):
    eligible_count: int = Field(ge=0)
    evaluated_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    exclusion_reasons: tuple[str, ...] = ()
    metric: RankingMetric | None = None
    period: AnswerPeriod | None = None
    direction: RankingDirection | None = None
    tie_break: str = "canonical entity ID ascending"

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.evaluated_count + self.excluded_count != self.eligible_count:
            raise ValueError("evaluated and excluded counts must equal eligible count")
        if self.excluded_count and not self.exclusion_reasons:
            raise ValueError("excluded entities require an exclusion reason")
        return self


class AnalysisResponse(AnalysisModel):
    request: AnalysisRequest
    snapshot_id: str = Field(min_length=1)
    status: AnalysisStatus
    answer: str = Field(min_length=1)
    findings: tuple[AnalysisFinding, ...] = ()
    recommendations: tuple[AnalysisRecommendation, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    unsupported_parts: tuple[str, ...] = ()
    explanation: AnalysisExplanation | None = None
    explanation_value: ExplanationValue = ExplanationValue.NOT_INVOKED
    presentation: AnalysisPresentation | None = None
    population: AnalysisPopulation | None = None
    generated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        finding_ids = [item.finding_id for item in self.findings]
        recommendation_ids = [item.recommendation_id for item in self.recommendations]
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("finding IDs must be unique")
        if len(set(recommendation_ids)) != len(recommendation_ids):
            raise ValueError("recommendation IDs must be unique")
        finding_set = set(finding_ids)
        recommendation_set = set(recommendation_ids)
        if any(
            not set(item.recommendation_ids).issubset(recommendation_set) for item in self.findings
        ):
            raise ValueError("finding references an unknown recommendation")
        if any(
            not set(item.supporting_finding_ids).issubset(finding_set)
            for item in self.recommendations
        ):
            raise ValueError("recommendation references an unknown finding")
        if self.presentation is not None:
            if (
                self.presentation.decisive_finding_id is not None
                and self.presentation.decisive_finding_id not in finding_set
            ):
                raise ValueError("presentation references an unknown finding")
            if (
                self.presentation.recommendation_id is not None
                and self.presentation.recommendation_id not in recommendation_set
            ):
                raise ValueError("presentation references an unknown recommendation")
        return self
