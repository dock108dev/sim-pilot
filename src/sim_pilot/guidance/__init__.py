"""Game-neutral contracts for teaching, advising, and explicit delegation."""

from .models import (
    CapabilityEvidenceStage,
    CrashCourseResponse,
    DelegationResult,
    EvidenceKind,
    EvidenceReference,
    GuidanceStatus,
    GuidedActionCapability,
    GuidedCapabilityView,
    InteractionClassification,
    InteractionKind,
    KnowledgeClaim,
    KnowledgeVerificationStage,
    QuestionResponse,
    Recommendation,
    RecommendationResponse,
)

__all__ = [
    "CapabilityEvidenceStage",
    "CrashCourseResponse",
    "DelegationResult",
    "EvidenceKind",
    "EvidenceReference",
    "GuidedActionCapability",
    "GuidedCapabilityView",
    "GuidanceStatus",
    "InteractionClassification",
    "InteractionKind",
    "KnowledgeClaim",
    "KnowledgeVerificationStage",
    "QuestionResponse",
    "Recommendation",
    "RecommendationResponse",
]
