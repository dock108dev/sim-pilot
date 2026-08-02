"""Explicit, capability-gated delegation to live-proven Software Inc. UI actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sim_pilot.guidance import DelegationResult, GuidanceStatus, RecommendationResponse
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError
from sim_pilot.software_inc.ui.controller import execute_ui_action, parse_ui_action
from sim_pilot.software_inc.ui.models import SoftwareIncUIAction, SoftwareIncUIDoResult
from sim_pilot.software_inc.ui.office import parse_office_intent
from sim_pilot.software_inc.ui.staffing import parse_staffing_intent

from .capabilities import action_capability
from .context import SoftwareIncGuidanceContext

type UIExecutor = Callable[[SoftwareIncUIAction], Awaitable[SoftwareIncUIDoResult]]


async def _default_executor(action: SoftwareIncUIAction) -> SoftwareIncUIDoResult:
    return await execute_ui_action(action)


class SoftwareIncDelegationService:
    def __init__(self, executor: UIExecutor = _default_executor) -> None:
        self._executor = executor

    async def delegate(
        self,
        objective: str,
        context: SoftwareIncGuidanceContext,
        *,
        recommendation: RecommendationResponse | None = None,
    ) -> DelegationResult:
        normalized = " ".join(objective.strip().casefold().split())
        if normalized in {"use your recommended plan", "use the recommended plan"}:
            resolved = self._resolve_recommendation(recommendation, context)
            if isinstance(resolved, DelegationResult):
                return resolved
            action = resolved
            assert recommendation is not None
            assert recommendation.recommended is not None
            effective_objective = recommendation.recommended.objective
        else:
            effective_objective = objective
            try:
                action = parse_ui_action(objective)
            except SoftwareIncUIValidationError:
                try:
                    staffing = parse_staffing_intent(objective)
                except SoftwareIncUIValidationError:
                    try:
                        office = parse_office_intent(objective)
                    except SoftwareIncUIValidationError:
                        return DelegationResult(
                            status=GuidanceStatus.UNSUPPORTED,
                            objective=objective,
                            verified=False,
                            message=(
                                "Unsupported Software Inc. delegation. Use `/capabilities` for "
                                "the currently proven action boundary."
                            ),
                        )
                    action = SoftwareIncUIAction(office.action)
                else:
                    action = SoftwareIncUIAction(staffing.action)
        capability = action_capability(context.capabilities, action.value)
        if capability is None or not capability.direct_ui_action:
            return DelegationResult(
                status=GuidanceStatus.UNSUPPORTED,
                objective=effective_objective,
                action=action.value,
                verified=False,
                message=f"{action.value} is not a recognized direct UI capability.",
            )
        if not capability.live_verified:
            return DelegationResult(
                status=GuidanceStatus.BLOCKED,
                objective=effective_objective,
                action=action.value,
                verified=False,
                message=(
                    f"{action.value} is implemented and offline-tested but its live mutation "
                    "gate is pending. No UI input was sent and no approval was created."
                ),
            )
        if not capability.compatible or context.state is None:
            return DelegationResult(
                status=GuidanceStatus.BLOCKED,
                objective=effective_objective,
                action=action.value,
                verified=False,
                message=(
                    "The exact compatible live Software Inc. save is unavailable. No UI input "
                    "was sent."
                ),
            )
        result = await self._executor(action)
        return DelegationResult(
            status=GuidanceStatus.COMPLETED if result.verified else GuidanceStatus.BLOCKED,
            objective=effective_objective,
            action=action.value,
            gestures_sent=result.gestures_sent,
            verified=result.verified,
            message=result.message,
        )

    def _resolve_recommendation(
        self,
        recommendation: RecommendationResponse | None,
        context: SoftwareIncGuidanceContext,
    ) -> SoftwareIncUIAction | DelegationResult:
        if recommendation is None or recommendation.recommended is None:
            return DelegationResult(
                status=GuidanceStatus.BLOCKED,
                objective="use your recommended plan",
                verified=False,
                message="There is no current recommendation to delegate. Run `/recommend` first.",
            )
        item = recommendation.recommended
        if not recommendation.is_current(datetime.now(UTC)):
            return DelegationResult(
                status=GuidanceStatus.BLOCKED,
                objective=item.objective,
                action=item.action,
                verified=False,
                message="The current recommendation expired. Run `/recommend` again.",
            )
        if not item.executable or item.action is None:
            return DelegationResult(
                status=GuidanceStatus.BLOCKED,
                objective=item.objective,
                verified=False,
                message="The current recommendation is advisory only and cannot be executed.",
            )
        state = context.state
        if (
            state is None
            or recommendation.game_session_id != state.game_session_id
            or recommendation.save_identity != state.save_identity
            or recommendation.capability_fingerprint != context.capabilities.capability_fingerprint
        ):
            return DelegationResult(
                status=GuidanceStatus.BLOCKED,
                objective=item.objective,
                action=item.action,
                verified=False,
                message=(
                    "The save, session, or capability boundary changed after recommendation. "
                    "Run `/recommend` again."
                ),
            )
        return SoftwareIncUIAction(item.action)


__all__ = ["SoftwareIncDelegationService", "UIExecutor"]
