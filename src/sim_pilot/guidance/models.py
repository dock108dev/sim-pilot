"""Strict game-neutral contracts for guided player interaction."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class GuidanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class InteractionKind(StrEnum):
    QUESTION = "question"
    CRASH_COURSE = "crash_course"
    STATUS = "status"
    RECOMMENDATION = "recommendation"
    EXPLANATION = "explanation"
    DELEGATION = "delegation"
    CAPABILITIES = "capabilities"
    HELP = "help"
    QUIT = "quit"
    UNKNOWN = "unknown"


class GuidanceStatus(StrEnum):
    ANSWERED = "answered"
    COMPLETED = "completed"
    INSUFFICIENT_DATA = "insufficient_data"
    UNSUPPORTED = "unsupported"
    CLARIFICATION_REQUIRED = "clarification_required"
    BLOCKED = "blocked"


class EvidenceKind(StrEnum):
    LIVE_OBSERVATION = "live_observation"
    DETERMINISTIC_CALCULATION = "deterministic_calculation"
    VERIFIED_REPOSITORY_KNOWLEDGE = "verified_repository_knowledge"
    BOUNDED_INFERENCE = "bounded_inference"
    UNAVAILABLE = "unavailable"


class KnowledgeVerificationStage(StrEnum):
    UNKNOWN = "unknown"
    RESEARCHED = "researched"
    FIXTURE_VALIDATED = "fixture_validated"
    EXPERIMENTALLY_VERIFIED = "experimentally_verified"
    LIVE_REGRESSION_PROVEN = "live_regression_proven"


class CapabilityEvidenceStage(StrEnum):
    UNAVAILABLE = "unavailable"
    RESEARCHED = "researched"
    FIXTURE_VALIDATED = "fixture_validated"
    OFFLINE_INTEGRATION_TESTED = "offline_integration_tested"
    LIVE_READ_ONLY_VERIFIED = "live_read_only_verified"
    LIVE_MUTATION_VERIFIED = "live_mutation_verified"


class InteractionClassification(GuidanceModel):
    schema_version: Literal[1] = 1
    kind: InteractionKind
    normalized_input: str = Field(min_length=1, max_length=4096)
    deterministic: bool
    clarification_required: bool = False
    mutation_permitted: bool = False
    topic: str | None = Field(default=None, min_length=1, max_length=128)
    objective: str | None = Field(default=None, min_length=1, max_length=2048)
    source: Literal["slash_command", "deterministic", "model"]

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if self.mutation_permitted and self.kind is not InteractionKind.DELEGATION:
            raise ValueError("only delegation classifications may permit mutation")
        if self.kind is InteractionKind.DELEGATION and not self.objective:
            raise ValueError("delegation requires an objective")
        return self


class EvidenceReference(GuidanceModel):
    schema_version: Literal[1] = 1
    evidence_id: str = Field(min_length=1, max_length=256)
    kind: EvidenceKind
    summary: str = Field(min_length=1, max_length=1024)
    source: str = Field(min_length=1, max_length=512)
    observed_value: str | None = Field(default=None, max_length=512)
    limitations: tuple[str, ...] = ()


class KnowledgeClaim(GuidanceModel):
    schema_version: Literal[1] = 1
    claim_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    game_id: str = Field(min_length=1, max_length=128)
    supported_versions: tuple[str, ...]
    supported_builds: tuple[str, ...] = ()
    topic: str = Field(min_length=1, max_length=128)
    claim: str = Field(min_length=1, max_length=2048)
    prerequisites: tuple[str, ...] = ()
    applicability: str = Field(min_length=1, max_length=1024)
    provenance_type: Literal["official", "community_guide", "repository_evidence"]
    provenance_locator: str = Field(min_length=1, max_length=1024)
    verification_stage: KnowledgeVerificationStage
    confidence: Literal["low", "medium", "high"]
    last_verified: str | None = Field(default=None, max_length=64)
    related_observation_fields: tuple[str, ...] = ()
    related_actions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    supersedes: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if not self.supported_versions:
            raise ValueError("knowledge claim requires a supported game version")
        if tuple(sorted(set(self.supported_versions))) != self.supported_versions:
            raise ValueError("supported versions must be unique and sorted")
        if tuple(sorted(set(self.supported_builds))) != self.supported_builds:
            raise ValueError("supported builds must be unique and sorted")
        return self


class QuestionResponse(GuidanceModel):
    schema_version: Literal[1] = 1
    question: str = Field(min_length=1, max_length=4096)
    status: GuidanceStatus
    answer: str = Field(min_length=1, max_length=4096)
    evidence: tuple[EvidenceReference, ...] = ()
    limitation: str | None = Field(default=None, min_length=1, max_length=2048)
    follow_up: str | None = Field(default=None, min_length=1, max_length=1024)


class GuidedActionCapability(GuidanceModel):
    schema_version: Literal[1] = 1
    action: str = Field(min_length=1, max_length=128)
    semantic_action: bool = False
    direct_ui_action: bool = False
    persisted_task_action: bool = False
    offline_tested: bool
    live_verified: bool
    approval_required: bool
    evidence_stage: CapabilityEvidenceStage
    compatible: bool
    platform_boundary: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_live_stage(self) -> Self:
        if self.live_verified and self.evidence_stage not in {
            CapabilityEvidenceStage.LIVE_READ_ONLY_VERIFIED,
            CapabilityEvidenceStage.LIVE_MUTATION_VERIFIED,
        }:
            raise ValueError("live verified capability requires a live evidence stage")
        return self


class GuidedCapabilityView(GuidanceModel):
    schema_version: Literal[1] = 1
    game_id: str = Field(min_length=1, max_length=128)
    game_version: str | None = Field(default=None, max_length=128)
    steam_build_id: str | None = Field(default=None, max_length=128)
    observation_available: bool
    semantic_gameplay_actions: tuple[str, ...] = ()
    generic_task_runtime_available: bool
    actions: tuple[GuidedActionCapability, ...]
    knowledge_topics: tuple[str, ...]
    capability_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    limitations: tuple[str, ...] = ()


class CrashCourseResponse(GuidanceModel):
    schema_version: Literal[1] = 1
    topic: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    sections: tuple[str, ...] = Field(min_length=1)
    personalized: bool
    evidence: tuple[EvidenceReference, ...] = ()
    limitations: tuple[str, ...] = ()


class Recommendation(GuidanceModel):
    schema_version: Literal[1] = 1
    recommendation_id: str = Field(pattern=r"^recommendation:[0-9a-f]{20}$")
    title: str = Field(min_length=1, max_length=256)
    objective: str = Field(min_length=1, max_length=1024)
    expected_benefit: str = Field(min_length=1, max_length=1024)
    risk: str = Field(min_length=1, max_length=1024)
    prerequisites: tuple[str, ...]
    approval_required: bool
    executable: bool
    action: str | None = Field(default=None, min_length=1, max_length=128)
    capability_stage: CapabilityEvidenceStage
    evidence: tuple[EvidenceReference, ...]
    material_unknowns: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_executable_action(self) -> Self:
        if self.executable != (self.action is not None):
            raise ValueError("executable recommendation requires exactly one action")
        return self


class RecommendationResponse(GuidanceModel):
    schema_version: Literal[1] = 1
    status: GuidanceStatus
    rule_id: str = Field(min_length=1, max_length=128)
    recommended: Recommendation | None = None
    alternatives: tuple[Recommendation, ...] = Field(default=(), max_length=2)
    game_session_id: str | None = Field(default=None, max_length=128)
    save_identity: str | None = Field(default=None, max_length=256)
    source_snapshot_id: str | None = Field(default=None, max_length=128)
    capability_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    expires_at: AwareDatetime
    explanation: str = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.status is GuidanceStatus.ANSWERED and self.recommended is None:
            raise ValueError("answered recommendation requires an objective")
        if self.status is not GuidanceStatus.ANSWERED and self.recommended is not None:
            raise ValueError("non-answered recommendation cannot contain an objective")
        if self.expires_at <= self.created_at:
            raise ValueError("recommendation expiration must follow creation")
        return self

    def is_current(self, now: datetime) -> bool:
        return now < self.expires_at


class DelegationResult(GuidanceModel):
    schema_version: Literal[1] = 1
    status: GuidanceStatus
    objective: str = Field(min_length=1, max_length=2048)
    action: str | None = Field(default=None, min_length=1, max_length=128)
    gestures_sent: int = Field(default=0, ge=0)
    verified: bool
    message: str = Field(min_length=1, max_length=2048)
