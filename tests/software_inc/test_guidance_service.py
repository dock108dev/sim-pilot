"""Read-only guidance, recommendation, and bounded-delegation service tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sim_pilot.guidance import GuidanceStatus
from sim_pilot.software_inc.guidance.context import (
    SoftwareIncGuidanceContext,
    SoftwareIncGuidanceContextProvider,
)
from sim_pilot.software_inc.guidance.delegation import SoftwareIncDelegationService, UIExecutor
from sim_pilot.software_inc.guidance.knowledge import SoftwareIncKnowledgeProvider
from sim_pilot.software_inc.guidance.service import SoftwareIncGuidanceService
from sim_pilot.software_inc.ui.models import (
    SoftwareIncUIAction,
    SoftwareIncUIDoResult,
)
from tests.software_inc.guidance_helpers import guidance_context, ui_observation


class StaticContextProvider(SoftwareIncGuidanceContextProvider):
    def __init__(self, context: SoftwareIncGuidanceContext) -> None:
        self.context = context
        self.knowledge = SoftwareIncKnowledgeProvider()

    async def load(self) -> SoftwareIncGuidanceContext:
        return self.context


def service_for(
    context: SoftwareIncGuidanceContext,
    *,
    executor: UIExecutor | None = None,
) -> SoftwareIncGuidanceService:
    delegation = (
        SoftwareIncDelegationService(executor=executor)
        if executor is not None
        else SoftwareIncDelegationService()
    )
    return SoftwareIncGuidanceService(
        context_provider=StaticContextProvider(context),
        delegation=delegation,
    )


def test_questions_and_recommendations_make_zero_ui_calls() -> None:
    calls: list[SoftwareIncUIAction] = []

    async def forbidden(action: SoftwareIncUIAction) -> SoftwareIncUIDoResult:
        calls.append(action)
        raise AssertionError("read-only guidance called the UI executor")

    service = service_for(guidance_context(), executor=forbidden)

    team_answer = asyncio.run(service.ask("What do teams do?"))
    count_answer = asyncio.run(service.ask("How many employees do I have?"))
    recommendation = asyncio.run(service.recommend())
    explanation = asyncio.run(service.explain(recommendation))

    assert team_answer.status is GuidanceStatus.ANSWERED
    assert count_answer.answer == "You have 1 observed employee."
    assert recommendation.recommended is not None
    assert recommendation.recommended.action == "open_manage_teams"
    assert explanation.status is GuidanceStatus.ANSWERED
    assert calls == []


def test_crash_course_personalizes_and_falls_back_without_live_state() -> None:
    live = service_for(guidance_context())
    offline = service_for(guidance_context(live_state=False))

    live_course = asyncio.run(live.crash_course("company"))
    fallback = asyncio.run(offline.crash_course("company"))
    hiring = asyncio.run(live.crash_course("hiring"))
    testing = asyncio.run(live.crash_course("testing", testing=True))
    office = asyncio.run(live.crash_course("office"))
    schedules = asyncio.run(live.crash_course("schedules"))
    servers = asyncio.run(live.crash_course("servers"))
    training = asyncio.run(live.crash_course("training"))

    assert live_course.personalized is True
    assert any("Fixture Labs" in section for section in live_course.sections)
    assert fallback.personalized is False
    assert any("personalization unavailable" in item for item in fallback.limitations)
    assert any("separate" in section.casefold() for section in hiring.sections)
    assert any("create_team=offline_integration_tested" in item for item in testing.sections)
    assert any("Semantic gameplay actions: none" in item for item in testing.sections)
    assert any("workstation" in section.casefold() for section in office.sections)
    assert any("whole-hour" in section.casefold() for section in schedules.sections)
    assert any("source-control" in section.casefold() for section in servers.sections)
    assert any("designer/system" in section.casefold() for section in training.sections)
    assert any("always returns the game to pause" in section for section in training.sections)


def test_training_questions_and_course_never_send_ui_input() -> None:
    calls: list[SoftwareIncUIAction] = []

    async def forbidden(action: SoftwareIncUIAction) -> SoftwareIncUIDoResult:
        calls.append(action)
        raise AssertionError("training guidance called the UI executor")

    service = service_for(guidance_context(), executor=forbidden)

    model = asyncio.run(service.ask("How does training work?"))
    specialization = asyncio.run(service.ask("What is System design?"))
    suitability = asyncio.run(service.ask("Who should I train?"))
    course = asyncio.run(service.crash_course("training"))

    assert model.status is GuidanceStatus.ANSWERED
    assert specialization.status is GuidanceStatus.ANSWERED
    assert suitability.status is GuidanceStatus.ANSWERED
    assert course.personalized is True
    assert calls == []


def test_office_questions_use_current_save_and_do_not_send_ui_input() -> None:
    calls: list[SoftwareIncUIAction] = []

    async def forbidden(action: SoftwareIncUIAction) -> SoftwareIncUIDoResult:
        calls.append(action)
        raise AssertionError("office question called the UI executor")

    service = service_for(guidance_context(), executor=forbidden)

    hours = asyncio.run(service.ask("What hours does Core work?"))
    capacity = asyncio.run(service.ask("Does Core have enough desks?"))
    server = asyncio.run(service.ask("Does this team need a server?"))
    ambiguous_employee = asyncio.run(service.ask("Why isn't this employee working?"))

    assert "8" in hours.answer and "16" in hours.answer
    assert capacity.answer.startswith("Yes.")
    assert "No universal" in server.answer
    assert ambiguous_employee.status is GuidanceStatus.INSUFFICIENT_DATA
    assert calls == []


def test_observed_facts_encoded_knowledge_and_unknowns_are_labeled() -> None:
    service = service_for(guidance_context())

    observed = asyncio.run(service.ask("How much cash do I have?"))
    knowledge = asyncio.run(service.ask("Why would I hire a programmer?"))
    unknown = asyncio.run(service.ask("What is the best stock strategy?"))
    financial = asyncio.run(service.ask("Am I in financial trouble?"))

    assert {item.kind.value for item in observed.evidence} == {"live_observation"}
    assert {item.kind.value for item in knowledge.evidence} == {"verified_repository_knowledge"}
    assert unknown.status is GuidanceStatus.UNSUPPORTED
    assert financial.status is GuidanceStatus.INSUFFICIENT_DATA
    assert "Rent" in (financial.limitation or "")


def test_version_or_build_mismatched_knowledge_is_not_presented_as_applicable() -> None:
    context = guidance_context()
    mismatched = replace(
        context,
        discovery=context.discovery.model_copy(
            update={"product_version": "1.9.0", "steam_build_id": "future-build"}
        ),
    )

    result = asyncio.run(service_for(mismatched).ask("What do teams do?"))

    assert result.status is GuidanceStatus.INSUFFICIENT_DATA
    assert "not verified for the detected game identity" in result.answer


def test_recommendation_requires_complete_current_state_and_matching_bridge() -> None:
    incomplete = service_for(guidance_context(complete_employees=False))
    mismatch = service_for(guidance_context(artifact_matches=False, paused=False))

    incomplete_result = asyncio.run(incomplete.recommend())
    mismatch_result = asyncio.run(mismatch.recommend())

    assert incomplete_result.status is GuidanceStatus.INSUFFICIENT_DATA
    assert mismatch_result.recommended is not None
    assert mismatch_result.recommended.executable is False
    assert mismatch_result.recommended.action is None


def test_explicit_live_delegation_hands_off_once_and_verifies() -> None:
    calls: list[SoftwareIncUIAction] = []

    async def executor(action: SoftwareIncUIAction) -> SoftwareIncUIDoResult:
        calls.append(action)
        observation = ui_observation()
        return SoftwareIncUIDoResult(
            action=action,
            before=observation,
            after=observation,
            gestures_sent=1,
            cycles=1,
            dry_run=False,
            verified=True,
            message="Manage Teams opened and verified.",
            completed_at=datetime.now(UTC),
        )

    service = service_for(guidance_context(), executor=executor)
    result = asyncio.run(service.operate("open manage teams"))

    assert result.status is GuidanceStatus.COMPLETED
    assert result.verified is True
    assert result.gestures_sent == 1
    assert calls == [SoftwareIncUIAction.OPEN_MANAGE_TEAMS]


def test_pending_and_unsupported_delegations_fail_closed_without_ui() -> None:
    calls: list[SoftwareIncUIAction] = []

    async def forbidden(action: SoftwareIncUIAction) -> SoftwareIncUIDoResult:
        calls.append(action)
        raise AssertionError("blocked delegation called the UI executor")

    service = service_for(guidance_context(), executor=forbidden)
    pending = asyncio.run(
        service.operate("Hire one programmer for Support Alpha for no more than $8,000 per month")
    )
    unsupported = asyncio.run(service.operate("release the product"))

    assert pending.status is GuidanceStatus.BLOCKED
    assert "live mutation gate is pending" in pending.message
    assert unsupported.status is GuidanceStatus.UNSUPPORTED
    assert calls == []


def test_recommendation_delegation_rejects_changed_save_identity() -> None:
    original = service_for(guidance_context())
    recommendation = asyncio.run(original.recommend())
    changed = service_for(guidance_context(save="another-save"))

    result = asyncio.run(
        changed.operate(
            "use your recommended plan",
            recommendation=recommendation,
        )
    )

    assert result.status is GuidanceStatus.BLOCKED
    assert "changed after recommendation" in result.message


def test_recommendation_delegation_rejects_expired_context() -> None:
    service = service_for(guidance_context())
    recommendation = asyncio.run(service.recommend())
    now = datetime.now(UTC)
    expired = recommendation.model_copy(
        update={"created_at": now - timedelta(minutes=10), "expires_at": now - timedelta(minutes=5)}
    )

    result = asyncio.run(service.operate("use your recommended plan", recommendation=expired))

    assert result.status is GuidanceStatus.BLOCKED
    assert "expired" in result.message
