"""Application facade and concise rendering for Software Inc. guided interaction."""

from __future__ import annotations

from pydantic import BaseModel

from sim_pilot.guidance import (
    CrashCourseResponse,
    DelegationResult,
    GuidanceStatus,
    GuidedCapabilityView,
    QuestionResponse,
    RecommendationResponse,
)

from .context import SoftwareIncGuidanceContextProvider
from .delegation import SoftwareIncDelegationService
from .read_service import SoftwareIncReadGuidanceService


class SoftwareIncGuidanceService:
    def __init__(
        self,
        *,
        context_provider: SoftwareIncGuidanceContextProvider | None = None,
        delegation: SoftwareIncDelegationService | None = None,
    ) -> None:
        self.context_provider = context_provider or SoftwareIncGuidanceContextProvider()
        self.read = SoftwareIncReadGuidanceService(self.context_provider.knowledge)
        self.delegation = delegation or SoftwareIncDelegationService()

    async def ask(self, question: str) -> QuestionResponse:
        return self.read.answer(question, await self.context_provider.load())

    async def status(self) -> QuestionResponse:
        return self.read.status(await self.context_provider.load())

    async def crash_course(
        self, topic: str = "company", *, testing: bool = False
    ) -> CrashCourseResponse:
        return self.read.crash_course(topic, await self.context_provider.load(), testing=testing)

    async def capabilities(self) -> GuidedCapabilityView:
        return (await self.context_provider.load()).capabilities

    async def recommend(self) -> RecommendationResponse:
        return self.read.recommend(await self.context_provider.load())

    async def explain(self, recommendation: RecommendationResponse | None) -> QuestionResponse:
        return self.read.explain(recommendation, await self.context_provider.load())

    async def operate(
        self,
        objective: str,
        *,
        recommendation: RecommendationResponse | None = None,
    ) -> DelegationResult:
        return await self.delegation.delegate(
            objective,
            await self.context_provider.load(),
            recommendation=recommendation,
        )


def render_guidance(value: BaseModel) -> str:
    if isinstance(value, QuestionResponse):
        lines = [value.answer]
        if value.limitation:
            lines.append(f"Limitation: {value.limitation}")
        if value.follow_up:
            lines.append(f"Try: {value.follow_up}")
        return "\n".join(lines)
    if isinstance(value, CrashCourseResponse):
        lines = [
            value.title,
            *(f"{index}. {section}" for index, section in enumerate(value.sections, 1)),
        ]
        lines.extend(f"Limitation: {item}" for item in value.limitations)
        return "\n".join(lines)
    if isinstance(value, GuidedCapabilityView):
        lines = [
            f"Software Inc. {value.game_version or 'unknown'} capabilities",
            f"Observation available: {str(value.observation_available).lower()}",
            "Semantic gameplay actions: none",
            "Generic persisted-task runtime: "
            f"{'available' if value.generic_task_runtime_available else 'unavailable'}",
        ]
        lines.extend(
            f"- {action.action}: {action.evidence_stage.value}; "
            f"currently_compatible={str(action.compatible).lower()}"
            for action in value.actions
        )
        lines.extend(f"Limitation: {item}" for item in value.limitations)
        return "\n".join(lines)
    if isinstance(value, RecommendationResponse):
        if value.status is not GuidanceStatus.ANSWERED or value.recommended is None:
            return value.explanation
        item = value.recommended
        lines = [
            f"Recommended: {item.title}",
            f"Why: {value.explanation}",
            f"Risk: {item.risk}",
            f"Executable now: {str(item.executable).lower()}",
        ]
        if item.material_unknowns:
            lines.append("Unknowns: " + " ".join(item.material_unknowns))
        if item.executable:
            lines.append("Try: /operate use your recommended plan")
        return "\n".join(lines)
    if isinstance(value, DelegationResult):
        return (
            f"{value.message}\n"
            f"action={value.action or 'none'}; gestures={value.gestures_sent}; "
            f"verified={str(value.verified).lower()}"
        )
    return value.model_dump_json(indent=2)


__all__ = ["SoftwareIncGuidanceService", "render_guidance"]
