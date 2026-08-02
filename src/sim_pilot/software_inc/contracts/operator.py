"""Verified visible-UI operator for one Software Inc. contract."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import uuid4

from sim_pilot.computer_control.models import DesktopFrame, InputGesture, InputGestureKind
from sim_pilot.game_bridge import CoverageStatus, GameSnapshot, ObservedEntity
from sim_pilot.software_inc.errors import (
    SoftwareIncUIObservationError,
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    VisualTarget,
)
from sim_pilot.software_inc.ui.observer import ObservedSoftwareIncUI, SoftwareIncUIObserver

from .models import (
    ContractApproval,
    ContractCommitment,
    ContractCycleEvent,
    ContractOperationResult,
    ContractRecommendation,
    ContractStage,
    ContractWorkflow,
    ContractWorkflowStatus,
)
from .projection import active_contract_work, available_contracts
from .store import ContractWorkflowStore
from .workflow import approval_for, create_workflow, resolve_approval, synchronize_workflow

ApprovalProvider = Callable[[ContractApproval], bool]


class ContractInputBackend(Protocol):
    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> object: ...


class ContractObserver(Protocol):
    @property
    def backend(self) -> ContractInputBackend: ...

    async def observe(self) -> ObservedSoftwareIncUI: ...

    async def keep_game_foreground(self) -> None: ...


ObserverFactory = Callable[[], ContractObserver]
_MAX_ACCEPT_CYCLES = 16
_POST_GESTURE_SETTLE_SECONDS = 0.1


async def browse_contracts(
    *,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
) -> ContractOperationResult:
    """Pause and open the visible Contracts window with one gesture per fresh cycle."""
    observer = observer_factory()
    current = await observer.observe()
    gestures = 0
    for _ in range(3):  # noqa: SIM113 - gestures counts only sent inputs
        _require_actionable(current.observation)
        if current.observation.scene is SoftwareIncUIScene.CONTRACT_BROWSER:
            available_contracts(current.observation.semantic_after)
            return _result(
                None,
                gestures,
                True,
                False,
                "Contracts are visibly open and every available row is semantically observed.",
            )
        if current.observation.scene is SoftwareIncUIScene.GAMEPLAY_RUNNING:
            target = _target(current.observation, "pause_button")
            effect = "pause before browsing contracts"
        elif current.observation.scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
            target = _target(current.observation, "open_contracts")
            effect = "open the visible Contracts window"
        else:
            raise SoftwareIncUIValidationError(
                "close the current management window before browsing contracts; "
                f"scene={current.observation.scene.value}"
            )
        if dry_run:
            return _result(
                None,
                0,
                False,
                True,
                f"Dry run: next verified gesture would {effect}.",
            )
        current = await _click(observer, current, target, effect)
        gestures += 1  # noqa: SIM113 - only successful input counts
    raise SoftwareIncUIVerificationError("Contracts window did not become observable within bounds")


async def accept_recommended_contract(
    recommendation: ContractRecommendation,
    *,
    approval_provider: ApprovalProvider | None,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ContractWorkflowStore | None = None,
) -> ContractOperationResult:
    """Configure and accept exactly one recommendation through visible UI controls."""
    if recommendation.recommended is None:
        raise SoftwareIncUIValidationError("there is no eligible contract to accept")
    repository = store or ContractWorkflowStore()
    observer = observer_factory()
    current = await observer.observe()
    await _ensure_recommendation_current(recommendation, current.observation.semantic_after)
    proposed = create_workflow(current.observation.semantic_after, recommendation.recommended)
    persisted = repository.get(proposed.workflow_id)
    if persisted is not None:
        _require_same_acceptance_workflow(persisted, proposed)
        workflow = persisted
    else:
        workflow = proposed
    repository.save(workflow)
    gestures = 0
    event_sequence = len(repository.events(workflow.workflow_id)) + 1
    configuring: str | None = None

    for _ in range(_MAX_ACCEPT_CYCLES):  # noqa: SIM113 - gestures counts only sent inputs
        observation = current.observation
        _require_actionable(observation)
        snapshot = observation.semantic_after
        active = _matching_work(snapshot, workflow)
        if active is not None:
            updated = workflow.model_copy(
                update={
                    "accepted_at": workflow.accepted_at or datetime.now(UTC),
                    "last_bridge_sequence": snapshot.bridge_sequence,
                    "observed_stage": active.stage,
                    "status": ContractWorkflowStatus.ACTIVE,
                    "work_item_id": active.work_item_id,
                    "updated_at": datetime.now(UTC),
                }
            )
            repository.save(updated)
            return _result(
                updated,
                gestures,
                True,
                False,
                f"Accepted {updated.contract_name!r}; exact active work item "
                f"{active.work_item_id} is assigned to {updated.team_name}.",
            )

        if not observation.paused:
            target = _target(observation, "pause_button")
            effect = "pause before contract configuration"
        elif observation.scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
            target = _target(observation, "open_contracts")
            effect = "open Contracts"
        elif observation.scene is SoftwareIncUIScene.CONTRACT_TEAM_SELECTION:
            selected = {
                value
                for value in _contract_ui_text(snapshot, "team_picker_selected").split("|")
                if value
            }
            unwanted_teams = sorted(
                value for value in selected if value.casefold() != workflow.team_name.casefold()
            )
            if unwanted_teams:
                target = _target(observation, f"contract_team_{unwanted_teams[0]}")
                effect = f"remove unapproved team {unwanted_teams[0]} from the contract"
            elif workflow.team_name.casefold() not in {value.casefold() for value in selected}:
                target = _target(observation, f"contract_team_{workflow.team_name}")
                effect = f"select only {workflow.team_name} in the contract team picker"
            else:
                target = _target(observation, "apply_contract_teams")
                effect = f"apply {workflow.team_name} as the {configuring or 'contract'} team"
        elif observation.scene is SoftwareIncUIScene.CONTRACT_BROWSER:
            contracts = available_contracts(snapshot)
            exact = [item for item in contracts if item.contract_id == workflow.contract_id]
            if len(exact) != 1:
                raise SoftwareIncUIValidationError(
                    "the approved contract disappeared or became ambiguous before acceptance"
                )
            index = exact[0].display_index
            selected = {
                value
                for value in _contract_ui_text(snapshot, "selected_available_indices").split(",")
                if value
            }
            design = {
                value for value in _contract_ui_text(snapshot, "design_teams").split("|") if value
            }
            development = {
                value
                for value in _contract_ui_text(snapshot, "development_teams").split("|")
                if value
            }
            if selected != {str(index)}:
                target = _target(observation, f"contract_row_{index}")
                effect = f"select only exact contract row {index}"
            elif {value.casefold() for value in design} != {workflow.team_name.casefold()}:
                target = _target(observation, "pick_contract_design_team")
                effect = "open design-team selection"
                configuring = "design"
            elif {value.casefold() for value in development} != {workflow.team_name.casefold()}:
                target = _target(observation, "pick_contract_development_team")
                effect = "open development-team selection"
                configuring = "development"
            else:
                prior_approval = workflow.pending_approval
                approval_reusable = (
                    prior_approval is not None
                    and prior_approval.commitment is ContractCommitment.ACCEPT
                    and prior_approval.approved is True
                    and prior_approval.plan_fingerprint == workflow.plan_fingerprint
                )
                pending = (
                    prior_approval
                    if approval_reusable
                    else approval_for(workflow, ContractCommitment.ACCEPT)
                )
                assert pending is not None
                if not approval_reusable:
                    workflow = workflow.model_copy(
                        update={
                            "pending_approval": pending,
                            "status": ContractWorkflowStatus.WAITING_FOR_APPROVAL,
                            "updated_at": datetime.now(UTC),
                        }
                    )
                    repository.save(workflow)
                if dry_run:
                    return _result(
                        workflow,
                        gestures,
                        False,
                        True,
                        "Dry run: team assignments are valid; the next irreversible step is "
                        "the exact acceptance approval.",
                    )
                if not approval_reusable and approval_provider is None:
                    return _result(
                        workflow,
                        gestures,
                        False,
                        True,
                        pending.action_summary,
                    )
                if not approval_reusable:
                    assert approval_provider is not None
                    workflow = resolve_approval(workflow, approved=approval_provider(pending))
                    repository.save(workflow)
                    if workflow.status is ContractWorkflowStatus.BLOCKED:
                        return _result(
                            workflow,
                            gestures,
                            False,
                            False,
                            "Contract acceptance was denied; no acceptance input was sent.",
                        )
                refreshed = await observer.observe()
                _require_continuity(observation, refreshed.observation)
                _require_actionable(refreshed.observation)
                _require_acceptance_commitment_current(workflow, refreshed.observation)
                current = refreshed
                target = _target(refreshed.observation, "commit_contract")
                effect = f"accept exact contract {workflow.contract_name!r}"
        else:
            raise SoftwareIncUIValidationError(
                f"contract acceptance cannot continue from scene {observation.scene.value}"
            )

        if dry_run:
            return _result(workflow, gestures, False, True, f"Dry run: would {effect}.")
        before_stage = workflow.observed_stage
        before_observation = current.observation
        current = await _click(observer, current, target, effect)
        gestures += 1  # noqa: SIM113 - only successful input counts
        if effect.startswith("select only exact contract row "):
            selected_after = {
                value
                for value in _contract_ui_text(
                    current.observation.semantic_after, "selected_available_indices"
                ).split(",")
                if value
            }
            expected_index = effect.rsplit(" ", 1)[-1]
            if selected_after != {expected_index}:
                raise SoftwareIncUIVerificationError(
                    "the exact contract-row input did not replace the observed selection; "
                    "it will not be retried"
                )
        elif effect.startswith("accept exact contract "):
            accepted = _matching_work(current.observation.semantic_after, workflow)
            if accepted is None:
                raise SoftwareIncUIVerificationError(
                    "the approved acceptance input did not create the exact contract work "
                    "item; it will not be retried"
                )
        workflow = workflow.model_copy(
            update={
                "last_bridge_sequence": current.observation.semantic_after.bridge_sequence,
                "updated_at": datetime.now(UTC),
            }
        )
        repository.save(workflow)
        repository.append_event(
            ContractCycleEvent(
                event_id=uuid4(),
                workflow_id=workflow.workflow_id,
                sequence=event_sequence,
                event_type="ui_gesture",
                bridge_sequence=current.observation.semantic_after.bridge_sequence,
                stage_before=before_stage,
                stage_after=workflow.observed_stage,
                action=effect,
                input_sent=True,
                verified=True,
                detail=(
                    "fresh synchronized observation completed after exactly one gesture; "
                    f"prior bridge sequence={before_observation.semantic_after.bridge_sequence}"
                ),
                recorded_at=datetime.now(UTC),
            )
        )
        event_sequence += 1
    raise SoftwareIncUIVerificationError("contract acceptance exceeded the bounded cycle limit")


async def promote_contract(
    workflow: ContractWorkflow,
    *,
    approval_provider: ApprovalProvider | None,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ContractWorkflowStore | None = None,
) -> ContractOperationResult:
    return await _commit_work_item_action(
        workflow,
        commitment=ContractCommitment.PROMOTE,
        target_suffix="promote",
        approval_provider=approval_provider,
        dry_run=dry_run,
        observer_factory=observer_factory,
        store=store,
    )


async def review_contract(
    workflow: ContractWorkflow,
    *,
    approval_provider: ApprovalProvider | None,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ContractWorkflowStore | None = None,
) -> ContractOperationResult:
    """Open and commit only the exact observed, approval-bound review configuration."""
    repository = store or ContractWorkflowStore()
    observer = observer_factory()
    before = await observer.observe()
    _require_actionable(before.observation)
    if not before.observation.paused:
        raise SoftwareIncUIValidationError(
            "pause the game before opening a contract review; no input was sent"
        )
    current = synchronize_workflow(workflow, before.observation.semantic_after)
    item_before = _matching_work(before.observation.semantic_after, current)
    if item_before is None or current.work_item_id is None:
        raise SoftwareIncUIValidationError("the exact active contract work item is unavailable")
    target_work_item_id = current.work_item_id
    if item_before.stage not in {ContractStage.ALPHA, ContractStage.BETA}:
        raise SoftwareIncUIValidationError(
            "review is supported only when the observed contract is in alpha or beta"
        )
    gestures = 0
    setup_preexisting = before.observation.scene is SoftwareIncUIScene.CONTRACT_REVIEW_SETUP
    if setup_preexisting:
        setup = before
    else:
        review_target_id = f"work-item-{target_work_item_id}-review"
        review_target = _optional_target(before.observation, review_target_id)
        if review_target is None:
            if dry_run:
                _target(before.observation, f"work-item-{target_work_item_id}-open")
                return _result(
                    current,
                    0,
                    False,
                    True,
                    "Dry run: would open the exact contract work-item controls before the "
                    "safe review action. No input was sent.",
                )
            card_target = _target(before.observation, f"work-item-{target_work_item_id}-open")
            opened = await _click(
                observer,
                before,
                card_target,
                f"open the exact {current.contract_name!r} work-item controls",
            )
            gestures += 1
            if not opened.observation.paused:
                raise SoftwareIncUIVerificationError(
                    "opening the contract work-item controls resumed game time"
                )
            opened_workflow = synchronize_workflow(current, opened.observation.semantic_after)
            opened_item = _matching_work(opened.observation.semantic_after, opened_workflow)
            if (
                opened_item is None
                or opened_item.work_item_id != item_before.work_item_id
                or opened_item.stage is not item_before.stage
                or opened_item.progress != item_before.progress
            ):
                raise SoftwareIncUIVerificationError(
                    "contract identity, stage, or progress changed while opening review controls"
                )
            current = opened_workflow
            before = opened
            review_target = _target(before.observation, review_target_id)
        if dry_run:
            return _result(
                current,
                0,
                False,
                True,
                "Dry run: the current frame exposes a safe review control; opening the review "
                "configuration would be the next reversible gesture. No input was sent.",
            )

        setup = await _click(observer, before, review_target, "open exact contract review setup")
        gestures += 1
        if setup.observation.scene is not SoftwareIncUIScene.CONTRACT_REVIEW_SETUP:
            raise SoftwareIncUIVerificationError(
                "the review control did not open the observed review configuration"
            )
    if not setup_preexisting:
        current = synchronize_workflow(current, setup.observation.semantic_after)
    repository.save(current)
    _append_event(
        repository,
        current,
        event_type=("review_setup_resumed" if setup_preexisting else "review_setup_opened"),
        bridge_sequence=setup.observation.semantic_after.bridge_sequence,
        stage_before=item_before.stage,
        stage_after=current.observed_stage,
        action=None if setup_preexisting else "open exact contract review setup",
        input_sent=not setup_preexisting,
        verified=True,
        detail="fresh review setup was observed before any spending approval",
    )
    cost = _review_cost(setup.observation.semantic_after)
    configuration = _review_configuration(setup.observation.semantic_after)
    pending = approval_for(
        current,
        ContractCommitment.REVIEW,
        one_time_cost=cost,
        configuration=configuration,
    )
    current = current.model_copy(
        update={
            "pending_approval": pending,
            "status": ContractWorkflowStatus.WAITING_FOR_APPROVAL,
            "updated_at": datetime.now(UTC),
        }
    )
    repository.save(current)
    if approval_provider is None:
        return _result(current, gestures, False, True, pending.action_summary)
    current = resolve_approval(current, approved=approval_provider(pending))
    repository.save(current)
    if current.status is ContractWorkflowStatus.BLOCKED:
        return _result(
            current,
            gestures,
            False,
            False,
            "Review spending was denied; the configuration was opened but no review was started.",
        )
    refreshed_setup = await observer.observe()
    _require_continuity(setup.observation, refreshed_setup.observation)
    _require_actionable(refreshed_setup.observation)
    if refreshed_setup.observation.scene is not SoftwareIncUIScene.CONTRACT_REVIEW_SETUP:
        raise SoftwareIncUIValidationError(
            "review configuration closed while approval was pending; no review input was sent"
        )
    refreshed_cost = _review_cost(refreshed_setup.observation.semantic_after)
    refreshed_configuration = _review_configuration(refreshed_setup.observation.semantic_after)
    if refreshed_cost != cost or refreshed_configuration != configuration:
        raise SoftwareIncUIValidationError(
            "review cost or configuration changed while approval was pending"
        )
    current = synchronize_workflow(current, refreshed_setup.observation.semantic_after)
    refreshed_item = _matching_work(refreshed_setup.observation.semantic_after, current)
    if (
        refreshed_item is None
        or refreshed_item.work_item_id != target_work_item_id
        or refreshed_item.stage is not item_before.stage
    ):
        raise SoftwareIncUIValidationError(
            "contract work changed while review approval was pending"
        )
    commit_target = _target(refreshed_setup.observation, "commit_contract_review")
    after = await _click(observer, refreshed_setup, commit_target, pending.action_summary)
    gestures += 1
    updated = synchronize_workflow(current, after.observation.semantic_after)
    item_after = _matching_work(after.observation.semantic_after, updated)
    review_work = _matching_review_work(after.observation.semantic_after, target_work_item_id)
    review_count_increased = (
        item_after is not None
        and item_before.reviews_done is not None
        and item_after.reviews_done is not None
        and item_after.reviews_done > item_before.reviews_done
    )
    if review_work is None and not review_count_increased:
        raise SoftwareIncUIVerificationError(
            "review commitment produced neither linked review work nor an increased review count"
        )
    repository.save(updated)
    _append_event(
        repository,
        updated,
        event_type="review_started",
        bridge_sequence=after.observation.semantic_after.bridge_sequence,
        stage_before=item_before.stage,
        stage_after=updated.observed_stage,
        action=pending.action_summary,
        input_sent=True,
        verified=True,
        detail=(
            f"review configuration {configuration}; observed one-time cost "
            f"${cost:,.2f}; linked_review_work={review_work is not None}"
        ),
    )
    return _result(
        updated,
        gestures,
        True,
        False,
        f"Review started and verified; configuration {configuration}; one-time cost ${cost:,.2f}.",
    )


async def release_contract(
    workflow: ContractWorkflow,
    *,
    approval_provider: ApprovalProvider | None,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ContractWorkflowStore | None = None,
) -> ContractOperationResult:
    return await _commit_work_item_action(
        workflow,
        commitment=ContractCommitment.RELEASE,
        target_suffix="release",
        approval_provider=approval_provider,
        dry_run=dry_run,
        observer_factory=observer_factory,
        store=store,
    )


async def advance_contract(
    workflow: ContractWorkflow,
    *,
    run_seconds: float = 10.0,
    deadline_risk_approval_provider: ApprovalProvider | None = None,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ContractWorkflowStore | None = None,
) -> ContractOperationResult:
    """Run a bounded interval, then pause and verify observed progress or bug movement."""
    if not 0 < run_seconds <= 30:
        raise SoftwareIncUIValidationError("contract run interval must be between 0 and 30 seconds")
    repository = store or ContractWorkflowStore()
    observer = observer_factory()
    before = await observer.observe()
    current_workflow = synchronize_workflow(workflow, before.observation.semantic_after)
    item_before = _matching_work(before.observation.semantic_after, current_workflow)
    if item_before is None:
        raise SoftwareIncUIValidationError("the active contract work item is not observed")
    gestures = 0
    reversible_scenes = {
        SoftwareIncUIScene.CONTRACT_BROWSER,
        SoftwareIncUIScene.BUILD_MODE,
        SoftwareIncUIScene.FURNITURE_PLACEMENT,
    }
    preflight_steps = 0
    while before.observation.scene in reversible_scenes:
        if preflight_steps >= 3:
            raise SoftwareIncUIVerificationError(
                "bounded contract preflight exceeded three reversible UI gestures"
            )
        scene = before.observation.scene
        if scene is SoftwareIncUIScene.CONTRACT_BROWSER:
            target_id = "close_contract_browser"
            effect = "close the Contracts window before bounded progression"
        elif scene is SoftwareIncUIScene.FURNITURE_PLACEMENT:
            target_id = "open_build_mode"
            effect = "cancel the furniture preview before bounded progression"
        else:
            target_id = "open_build_mode"
            effect = "close Build mode before bounded progression"
        if dry_run:
            return _result(
                current_workflow,
                0,
                False,
                True,
                f"Dry run: would {effect}.",
            )
        closed = await _click(
            observer,
            before,
            _target(before.observation, target_id),
            effect,
        )
        gestures += 1
        preflight_steps += 1
        if closed.observation.scene not in (
            SoftwareIncUIScene.GAMEPLAY_PAUSED,
            SoftwareIncUIScene.BUILD_MODE,
        ):
            raise SoftwareIncUIVerificationError(
                "reversible preflight did not reach paused gameplay or the next expected "
                "Build-mode step"
            )
        current_workflow = synchronize_workflow(current_workflow, closed.observation.semantic_after)
        item_after_close = _matching_work(closed.observation.semantic_after, current_workflow)
        if item_after_close is None or item_after_close.work_item_id != item_before.work_item_id:
            raise SoftwareIncUIVerificationError(
                "contract work changed while closing the Contracts window"
            )
        before = closed
        item_before = item_after_close
    if before.observation.scene is not SoftwareIncUIScene.GAMEPLAY_PAUSED:
        raise SoftwareIncUIValidationError(
            "bounded contract progression requires paused gameplay after reversible preflight"
        )
    completed_review = _completed_review_work(
        before.observation.semantic_after, item_before.work_item_id
    )
    if completed_review is not None:
        finish_target = _target(
            before.observation,
            f"work-item-{completed_review.entity_id}-finish-review",
        )
        if dry_run:
            return _result(
                current_workflow,
                gestures,
                False,
                True,
                "Dry run: would finish the exact completed review and observe its result; "
                "no input was sent.",
            )
        after_review = await _click(
            observer,
            before,
            finish_target,
            f"finish the completed review of {current_workflow.contract_name!r}",
        )
        gestures += 1
        updated = synchronize_workflow(current_workflow, after_review.observation.semantic_after)
        item_after_review = _matching_work(after_review.observation.semantic_after, updated)
        review_after = _completed_review_work(
            after_review.observation.semantic_after, item_before.work_item_id
        )
        review_count_increased = (
            item_after_review is not None
            and item_before.reviews_done is not None
            and item_after_review.reviews_done is not None
            and item_after_review.reviews_done > item_before.reviews_done
        )
        review_score_changed = (
            item_after_review is not None
            and item_after_review.review_score is not None
            and item_after_review.review_score != item_before.review_score
        )
        if review_after is not None and not review_count_increased and not review_score_changed:
            raise SoftwareIncUIVerificationError(
                "finishing the completed review produced no verified review outcome; "
                "the finish input will not be retried"
            )
        reviews_done_after = None if item_after_review is None else item_after_review.reviews_done
        review_score_after = None if item_after_review is None else item_after_review.review_score
        repository.save(updated)
        _append_event(
            repository,
            updated,
            event_type="review_finished",
            bridge_sequence=after_review.observation.semantic_after.bridge_sequence,
            stage_before=item_before.stage,
            stage_after=updated.observed_stage,
            action=f"finish completed review work item {completed_review.entity_id}",
            input_sent=True,
            verified=True,
            detail=(
                f"linked_review_removed={review_after is None}; "
                f"reviews_done={reviews_done_after}; review_score={review_score_after}"
            ),
        )
        return _result(
            updated,
            gestures,
            True,
            True,
            "Completed review was finished and its outcome was verified; "
            "no game time was advanced.",
        )
    if item_before.contract_started is False or item_before.days_remaining <= 5:
        pending = approval_for(current_workflow, ContractCommitment.DEADLINE_RISK)
        current_workflow = current_workflow.model_copy(
            update={
                "pending_approval": pending,
                "status": ContractWorkflowStatus.WAITING_FOR_APPROVAL,
                "updated_at": datetime.now(UTC),
            }
        )
        repository.save(current_workflow)
        if deadline_risk_approval_provider is None:
            return _result(
                current_workflow,
                0,
                False,
                True,
                "Deadline risk requires separate approval; no time-control input was sent.",
            )
        approved = deadline_risk_approval_provider(pending)
        current_workflow = resolve_approval(current_workflow, approved=approved)
        repository.save(current_workflow)
        if not approved:
            return _result(
                current_workflow,
                0,
                False,
                False,
                "Deadline-risk continuation was denied; no time-control input was sent.",
            )
        refreshed = await observer.observe()
        _require_continuity(before.observation, refreshed.observation)
        _require_actionable(refreshed.observation)
        if not refreshed.observation.paused:
            raise SoftwareIncUIValidationError(
                "game resumed while deadline-risk approval was pending; no input was sent"
            )
        current_workflow = synchronize_workflow(
            current_workflow, refreshed.observation.semantic_after
        )
        refreshed_item = _matching_work(refreshed.observation.semantic_after, current_workflow)
        if refreshed_item is None or refreshed_item.work_item_id != item_before.work_item_id:
            raise SoftwareIncUIValidationError(
                "contract work changed while deadline-risk approval was pending"
            )
        before = refreshed
        item_before = refreshed_item
    # Software Inc. 1.8.41 does not set DesignDocument.ContractStarted when the
    # project is unpaused. The flag changes only when an employee performs the
    # first unit of design work (or after the game's two-month fallback). Verify
    # the reversible project-pause transition here; verify ContractStarted only
    # after the separately approved bounded time interval below.
    if item_before.contract_started is False and item_before.paused:
        if dry_run:
            return _result(
                current_workflow,
                gestures,
                False,
                True,
                "Dry run: would activate the exact accepted work item and begin its approved "
                "deadline; no project or time-control input was sent.",
            )
        activated = await _click(
            observer,
            before,
            _target(
                before.observation,
                f"work-item-{item_before.work_item_id}-toggle-pause",
            ),
            "activate the accepted contract work item",
        )
        gestures += 1
        activated_workflow = synchronize_workflow(
            current_workflow, activated.observation.semantic_after
        )
        activated_item = _matching_work(activated.observation.semantic_after, activated_workflow)
        if activated_item is None or activated_item.work_item_id != item_before.work_item_id:
            raise SoftwareIncUIVerificationError(
                "the accepted contract work identity changed during activation"
            )
        if activated_item.paused:
            raise SoftwareIncUIVerificationError(
                "the verified project-level activation input did not unpause the work item; "
                "it will not be retried"
            )
        repository.save(activated_workflow)
        _append_event(
            repository,
            activated_workflow,
            event_type="contract_work_enabled",
            bridge_sequence=activated.observation.semantic_after.bridge_sequence,
            stage_before=item_before.stage,
            stage_after=activated_item.stage,
            action="activate the accepted contract work item",
            input_sent=True,
            verified=True,
            detail=(
                "project-level activation unpaused the exact work item; the deadline remains "
                "pending until the first observed employee work"
            ),
        )
        current_workflow = activated_workflow
        before = activated
        item_before = activated_item
    if dry_run:
        return _result(
            current_workflow,
            0,
            False,
            True,
            f"Dry run: would resume for at most {run_seconds:g} real seconds, then pause "
            "and re-observe.",
        )
    current = before
    if current.observation.paused:
        current = await _click(
            observer,
            current,
            _target(current.observation, "resume_button"),
            "resume bounded contract work",
        )
        gestures += 1
        resumed = synchronize_workflow(current_workflow, current.observation.semantic_after)
        repository.save(resumed)
        _append_event(
            repository,
            resumed,
            event_type="ui_gesture",
            bridge_sequence=current.observation.semantic_after.bridge_sequence,
            stage_before=item_before.stage,
            stage_after=resumed.observed_stage,
            action="resume bounded contract work",
            input_sent=True,
            verified=not current.observation.paused,
            detail="fresh synchronized running state followed the resume gesture",
        )
        current_workflow = resumed
    await observer.keep_game_foreground()
    await asyncio.sleep(run_seconds)
    current = await observer.observe()
    if not current.observation.paused:
        stage_before_pause = _matching_work(current.observation.semantic_after, current_workflow)
        current = await _click(
            observer,
            current,
            _target(current.observation, "pause_button"),
            "pause after bounded contract work",
        )
        gestures += 1
        paused_workflow = synchronize_workflow(current_workflow, current.observation.semantic_after)
        repository.save(paused_workflow)
        _append_event(
            repository,
            paused_workflow,
            event_type="ui_gesture",
            bridge_sequence=current.observation.semantic_after.bridge_sequence,
            stage_before=(
                current_workflow.observed_stage
                if stage_before_pause is None
                else stage_before_pause.stage
            ),
            stage_after=paused_workflow.observed_stage,
            action="pause after bounded contract work",
            input_sent=True,
            verified=current.observation.paused,
            detail="fresh synchronized paused state followed the pause gesture",
        )
        current_workflow = paused_workflow
    if current.observation.semantic_after.bridge_sequence > current_workflow.last_bridge_sequence:
        updated = synchronize_workflow(current_workflow, current.observation.semantic_after)
    else:
        updated = current_workflow
    item_after = _matching_work(current.observation.semantic_after, updated)
    if item_after is None:
        raise SoftwareIncUIVerificationError(
            "contract work disappeared without a completion result"
        )
    if item_before.contract_started is False and item_after.contract_started is not True:
        raise SoftwareIncUIVerificationError(
            "the bounded interval did not produce the first observed employee work, so the "
            "contract deadline is still unstarted"
        )
    changed = (
        item_after.progress != item_before.progress
        or item_after.bugs != item_before.bugs
        or item_after.fixed_bugs != item_before.fixed_bugs
        or item_after.stage != item_before.stage
    )
    repository.save(updated)
    _append_event(
        repository,
        updated,
        event_type="work_interval_verified",
        bridge_sequence=current.observation.semantic_after.bridge_sequence,
        stage_before=item_before.stage,
        stage_after=item_after.stage,
        action=None,
        input_sent=False,
        verified=True,
        detail=(
            f"progress {item_before.progress}->{item_after.progress}; bugs "
            f"{item_before.bugs}->{item_after.bugs}; fixed "
            f"{item_before.fixed_bugs}->{item_after.fixed_bugs}"
        ),
    )
    return _result(
        updated,
        gestures,
        True,
        not changed,
        (
            "Bounded work interval finished paused; progress "
            f"{item_before.progress}->{item_after.progress}, bugs "
            f"{item_before.bugs}->{item_after.bugs}, fixed "
            f"{item_before.fixed_bugs}->{item_after.fixed_bugs}."
        ),
    )


async def _commit_work_item_action(
    workflow: ContractWorkflow,
    *,
    commitment: ContractCommitment,
    target_suffix: str,
    approval_provider: ApprovalProvider | None,
    dry_run: bool,
    observer_factory: ObserverFactory,
    store: ContractWorkflowStore | None,
) -> ContractOperationResult:
    repository = store or ContractWorkflowStore()
    observer = observer_factory()
    before = await observer.observe()
    _require_actionable(before.observation)
    if not before.observation.paused:
        raise SoftwareIncUIValidationError(
            f"pause the game before {commitment.value}; no commitment input was sent"
        )
    current = synchronize_workflow(workflow, before.observation.semantic_after)
    item = _matching_work(before.observation.semantic_after, current)
    if item is None and commitment is ContractCommitment.RELEASE:
        completed_result = _matching_result(before.observation.semantic_after, current)
        if completed_result is not None:
            return _reconcile_completed_release(
                repository,
                current,
                before.observation.semantic_after,
                completed_result,
            )
    if item is None or current.work_item_id is None:
        raise SoftwareIncUIValidationError("the exact active contract work item is unavailable")
    promotion_is_explicitly_offered = (
        before.observation.scene is SoftwareIncUIScene.CONTRACT_REVIEW_RESULT
        and _optional_target(before.observation, "review_result_promote") is not None
    )
    if (
        commitment is ContractCommitment.PROMOTE
        and item.progress < item.minimum_progress
        and not promotion_is_explicitly_offered
    ):
        raise SoftwareIncUIValidationError(
            f"promotion rejected: observed progress {item.progress} is below the contract "
            f"minimum {item.minimum_progress}"
        )
    pending = approval_for(current, commitment)
    current = current.model_copy(
        update={
            "pending_approval": pending,
            "status": ContractWorkflowStatus.WAITING_FOR_APPROVAL,
            "updated_at": datetime.now(UTC),
        }
    )
    repository.save(current)
    if dry_run or approval_provider is None:
        return _result(current, 0, False, True, pending.action_summary)
    current = resolve_approval(current, approved=approval_provider(pending))
    repository.save(current)
    if current.status is ContractWorkflowStatus.BLOCKED:
        return _result(
            current, 0, False, False, f"{commitment.value.title()} was denied; no input was sent."
        )
    refreshed = await observer.observe()
    _require_continuity(before.observation, refreshed.observation)
    _require_actionable(refreshed.observation)
    if not refreshed.observation.paused:
        raise SoftwareIncUIValidationError(
            f"game resumed while {commitment.value} approval was pending; no input was sent"
        )
    current = synchronize_workflow(current, refreshed.observation.semantic_after)
    refreshed_item = _matching_work(refreshed.observation.semantic_after, current)
    if (
        refreshed_item is None
        or refreshed_item.work_item_id != item.work_item_id
        or refreshed_item.stage is not item.stage
    ):
        raise SoftwareIncUIValidationError(
            f"contract work changed while {commitment.value} approval was pending"
        )
    refreshed_promotion_is_explicitly_offered = (
        refreshed.observation.scene is SoftwareIncUIScene.CONTRACT_REVIEW_RESULT
        and _optional_target(refreshed.observation, "review_result_promote") is not None
    )
    if (
        commitment is ContractCommitment.PROMOTE
        and refreshed_item.progress < refreshed_item.minimum_progress
        and not refreshed_promotion_is_explicitly_offered
    ):
        raise SoftwareIncUIValidationError(
            "promotion eligibility changed while approval was pending"
        )
    gestures = 0
    target_id = f"work-item-{current.work_item_id}-{target_suffix}"
    target = (
        _optional_target(refreshed.observation, "review_result_promote")
        if commitment is ContractCommitment.PROMOTE
        and refreshed.observation.scene is SoftwareIncUIScene.CONTRACT_REVIEW_RESULT
        else _optional_target(refreshed.observation, target_id)
    )
    if target is None:
        card_target = _target(refreshed.observation, f"work-item-{current.work_item_id}-open")
        opened = await _click(
            observer,
            refreshed,
            card_target,
            f"open the exact {current.contract_name!r} work-item controls",
        )
        gestures += 1
        if not opened.observation.paused:
            raise SoftwareIncUIVerificationError(
                "opening the contract work-item controls resumed game time"
            )
        opened_workflow = synchronize_workflow(current, opened.observation.semantic_after)
        opened_item = _matching_work(opened.observation.semantic_after, opened_workflow)
        if (
            opened_item is None
            or opened_item.work_item_id != refreshed_item.work_item_id
            or opened_item.stage is not refreshed_item.stage
            or opened_item.progress != refreshed_item.progress
        ):
            raise SoftwareIncUIVerificationError(
                "contract identity, stage, or progress changed while opening its controls"
            )
        current = opened_workflow
        refreshed = opened
        target = _target(refreshed.observation, target_id)
    cash_before = _single_number(refreshed.observation.semantic_after, "finances", "cash")
    reputation_before = _single_number(
        refreshed.observation.semantic_after, "company", "business_reputation"
    )
    after = await _click(observer, refreshed, target, pending.action_summary)
    gestures += 1
    if after.observation.modal_state is ModalState.BLOCKING:
        pending_item = _matching_work(after.observation.semantic_after, current)
        if (
            pending_item is None
            or pending_item.work_item_id != refreshed_item.work_item_id
            or pending_item.stage is not refreshed_item.stage
        ):
            raise SoftwareIncUIVerificationError(
                "contract identity or stage changed before the commitment confirmation"
            )
        confirmation = _target(after.observation, "confirm_dialog_yes")
        after = await _click(
            observer,
            after,
            confirmation,
            f"confirm the already-approved {commitment.value} commitment",
        )
        gestures += 1
    updated = synchronize_workflow(current, after.observation.semantic_after)
    if commitment is ContractCommitment.PROMOTE and updated.observed_stage is item.stage:
        raise SoftwareIncUIVerificationError(
            "promotion input was not verified by a stage transition"
        )
    if commitment is ContractCommitment.RELEASE:
        result = _matching_result(after.observation.semantic_after, current)
        if result is None and updated.status is not ContractWorkflowStatus.COMPLETED:
            raise SoftwareIncUIVerificationError(
                "release input did not produce a completed result; no retry attempted"
            )
        if result is None:
            raise SoftwareIncUIVerificationError("completed contract result is unavailable")
        income = _entity_number(result, "income")
        final_result = _entity_number(result, "final_result")
        reputation_change = _entity_number(result, "reputation_change")
        cash_after = _single_number(after.observation.semantic_after, "finances", "cash")
        reputation_after = _single_number(
            after.observation.semantic_after, "company", "business_reputation"
        )
        if cash_before is None or cash_after is None:
            raise SoftwareIncUIVerificationError("release cash outcome is not observed")
        if abs((cash_after - cash_before) - income) > Decimal("0.02"):
            raise SoftwareIncUIVerificationError(
                "release cash delta does not match the completed contract payout"
            )
        if reputation_before is None or reputation_after is None:
            raise SoftwareIncUIVerificationError("release reputation outcome is not observed")
        status = result.values.get("status")
        late_penalty = _entity_number(result, "late_penalty")
        if not isinstance(status, str) or not status:
            raise SoftwareIncUIVerificationError("release deadline outcome is unavailable")
        updated = updated.model_copy(
            update={
                "status": ContractWorkflowStatus.COMPLETED,
                "completed_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        )
        release_detail = (
            f" status={status}; payout=${income:,.2f}; final_result=${final_result:,.2f}; "
            f"late_penalty=${late_penalty:,.2f}; "
            f"cash=${cash_after:,.2f}; reputation={reputation_after} "
            f"(result change={reputation_change})"
        )
    else:
        release_detail = ""
    repository.save(updated)
    _append_event(
        repository,
        updated,
        event_type=f"{commitment.value}_completed",
        bridge_sequence=after.observation.semantic_after.bridge_sequence,
        stage_before=item.stage,
        stage_after=updated.observed_stage,
        action=pending.action_summary,
        input_sent=True,
        verified=True,
        detail=(
            "visible work-item commitment verified by fresh semantic lifecycle and result state"
            + release_detail
        ),
    )
    return _result(
        updated,
        gestures,
        True,
        False,
        f"{commitment.value.title()} completed through the visible UI and verified "
        f"semantically.{release_detail}",
    )


def _reconcile_completed_release(
    repository: ContractWorkflowStore,
    workflow: ContractWorkflow,
    snapshot: GameSnapshot,
    result: ObservedEntity,
) -> ContractOperationResult:
    """Close an interrupted release after its exact completed result is already observed."""
    income = _entity_number(result, "income")
    final_result = _entity_number(result, "final_result")
    late_penalty = _entity_number(result, "late_penalty")
    reputation_change = _entity_number(result, "reputation_change")
    cash = _single_number(snapshot, "finances", "cash")
    reputation = _single_number(snapshot, "company", "business_reputation")
    status = result.values.get("status")
    if cash is None or reputation is None or not isinstance(status, str) or not status:
        raise SoftwareIncUIVerificationError(
            "completed contract result lacks current cash, reputation, or deadline outcome"
        )
    current = datetime.now(UTC)
    updated = workflow.model_copy(
        update={
            "completed_at": current,
            "last_bridge_sequence": snapshot.bridge_sequence,
            "observed_stage": ContractStage.COMPLETED,
            "pending_approval": None,
            "status": ContractWorkflowStatus.COMPLETED,
            "updated_at": current,
        }
    )
    repository.save(updated)
    detail = (
        f"Recovered an already-completed exact contract result without retrying release; "
        f"status={status}; payout=${income:,.2f}; final_result=${final_result:,.2f}; "
        f"late_penalty=${late_penalty:,.2f}; cash=${cash:,.2f}; reputation={reputation} "
        f"(result change={reputation_change})."
    )
    _append_event(
        repository,
        updated,
        event_type="release_reconciled",
        bridge_sequence=snapshot.bridge_sequence,
        stage_before=workflow.observed_stage,
        stage_after=ContractStage.COMPLETED,
        action=None,
        input_sent=False,
        verified=True,
        detail=detail,
    )
    return _result(updated, 0, True, False, detail)


async def _click(
    observer: ContractObserver,
    before: ObservedSoftwareIncUI,
    target: VisualTarget,
    effect: str,
) -> ObservedSoftwareIncUI:
    if target.point is None:
        raise SoftwareIncUIValidationError("current-frame target has no click point")
    frame = before.observation.frame
    gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=target.point,
        expected_process_id=frame.process_id,
        expected_window_id=frame.window_id,
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene=before.observation.scene.value,
        target_id=target.target_id,
        intended_effect=effect,
    )
    observer.backend.execute(gesture, frame=frame)
    # CoreGraphics posts asynchronously. Give the foreground Unity player one
    # frame to dispatch the click before requesting the verification snapshot.
    await asyncio.sleep(_POST_GESTURE_SETTLE_SECONDS)
    after = await observer.observe()
    _require_continuity(before.observation, after.observation)
    return after


def _target(observation: SoftwareIncUIObservation, target_id: str) -> VisualTarget:
    target = _optional_target(observation, target_id)
    if target is None:
        raise SoftwareIncUIValidationError(
            f"fresh target {target_id!r} did not resolve exactly once"
        )
    return target


def _optional_target(observation: SoftwareIncUIObservation, target_id: str) -> VisualTarget | None:
    matches = [target for target in observation.targets if target.target_id == target_id]
    if len(matches) != 1:
        return None
    target = matches[0]
    if (
        target.confidence < 0.8
        or target.source_frame_id != observation.frame.frame_id
        or target.expires_at <= datetime.now(UTC)
    ):
        raise SoftwareIncUIValidationError("contract target is stale or ambiguous")
    return target


def _require_actionable(observation: SoftwareIncUIObservation) -> None:
    if observation.modal_state is not ModalState.NONE:
        raise SoftwareIncUIObservationError(
            f"cannot operate contracts while modal state is {observation.modal_state.value}"
        )
    if observation.scene in {SoftwareIncUIScene.UNKNOWN, SoftwareIncUIScene.BLOCKING_MODAL}:
        raise SoftwareIncUIObservationError(
            f"cannot operate contracts from scene {observation.scene.value}"
        )


def _require_continuity(before: SoftwareIncUIObservation, after: SoftwareIncUIObservation) -> None:
    left = before.semantic_after
    right = after.semantic_after
    if (
        left.bridge_instance_id != right.bridge_instance_id
        or left.game_session_id != right.game_session_id
        or left.save_identity != right.save_identity
        or right.bridge_sequence <= left.bridge_sequence
        or before.frame.process_id != after.frame.process_id
        or before.frame.window_id != after.frame.window_id
    ):
        raise SoftwareIncUIVerificationError("save, session, bridge, window, or sequence changed")


async def _ensure_recommendation_current(
    recommendation: ContractRecommendation, snapshot: GameSnapshot
) -> None:
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    if (
        recommendation.expires_at <= datetime.now(UTC)
        or recommendation.game_session_id != snapshot.game_session_id
        or recommendation.save_identity != save_identity
        or snapshot.bridge_sequence < recommendation.source_bridge_sequence
    ):
        raise SoftwareIncUIValidationError("contract recommendation is expired or stale")


def _require_same_acceptance_workflow(
    persisted: ContractWorkflow,
    proposed: ContractWorkflow,
) -> None:
    if (
        persisted.plan_fingerprint != proposed.plan_fingerprint
        or persisted.game_session_id != proposed.game_session_id
        or persisted.save_identity != proposed.save_identity
        or persisted.contract_id != proposed.contract_id
        or persisted.contract_name != proposed.contract_name
        or persisted.client != proposed.client
        or persisted.team_name != proposed.team_name
        or persisted.minimum_reward != proposed.minimum_reward
        or persisted.minimum_cash_reserve != proposed.minimum_cash_reserve
        or persisted.reward != proposed.reward
        or persisted.maximum_penalty != proposed.maximum_penalty
        or persisted.deadline != proposed.deadline
    ):
        raise SoftwareIncUIValidationError(
            "persisted contract approval does not match the fresh exact recommendation"
        )
    if persisted.work_item_id is None and persisted.observed_stage is not ContractStage.AVAILABLE:
        raise SoftwareIncUIValidationError(
            "persisted contract workflow cannot safely resume acceptance"
        )


def _require_acceptance_commitment_current(
    workflow: ContractWorkflow,
    observation: SoftwareIncUIObservation,
) -> None:
    if not observation.paused or observation.scene is not SoftwareIncUIScene.CONTRACT_BROWSER:
        raise SoftwareIncUIValidationError(
            "contract scene changed while approval was pending; no acceptance input was sent"
        )
    contracts = available_contracts(observation.semantic_after)
    exact = [item for item in contracts if item.contract_id == workflow.contract_id]
    if len(exact) != 1:
        raise SoftwareIncUIValidationError(
            "approved contract disappeared or became ambiguous while approval was pending"
        )
    contract = exact[0]
    if (
        contract.name != workflow.contract_name
        or contract.client != workflow.client
        or contract.reward != workflow.reward
        or contract.penalty != workflow.maximum_penalty
        or contract.deadline != workflow.deadline
    ):
        raise SoftwareIncUIValidationError(
            "contract economics or deadline changed while approval was pending"
        )
    selected = {
        value
        for value in _contract_ui_text(
            observation.semantic_after, "selected_available_indices"
        ).split(",")
        if value
    }
    design = {
        value
        for value in _contract_ui_text(observation.semantic_after, "design_teams").split("|")
        if value
    }
    development = {
        value
        for value in _contract_ui_text(observation.semantic_after, "development_teams").split("|")
        if value
    }
    approved_team = {workflow.team_name.casefold()}
    if (
        selected != {str(contract.display_index)}
        or {value.casefold() for value in design} != approved_team
        or {value.casefold() for value in development} != approved_team
    ):
        raise SoftwareIncUIValidationError(
            "contract or team selection changed while approval was pending"
        )


def _matching_work(snapshot: GameSnapshot, workflow: ContractWorkflow):
    matches = [
        item
        for item in active_contract_work(snapshot)
        if item.contract_id == workflow.contract_id
        or (item.contract_name == workflow.contract_name and item.client == workflow.client)
    ]
    if len(matches) > 1:
        raise SoftwareIncUIValidationError("active contract work identity is ambiguous")
    return None if not matches else matches[0]


def _matching_result(snapshot: GameSnapshot, workflow: ContractWorkflow) -> ObservedEntity | None:
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == "contract_results"
    ]
    if len(surfaces) != 1 or surfaces[0].coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
        return None
    matches = [
        entity
        for entity in surfaces[0].entities
        if entity.entity_type == "contract_result"
        and entity.values.get("name") == workflow.contract_name
        and entity.values.get("client") == workflow.client
    ]
    if len(matches) > 1:
        raise SoftwareIncUIValidationError("completed contract result is ambiguous")
    return None if not matches else matches[0]


def _matching_review_work(
    snapshot: GameSnapshot, target_work_item_id: str
) -> ObservedEntity | None:
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == "work_items"
    ]
    if len(surfaces) != 1 or surfaces[0].coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
        return None
    matches = [
        entity
        for entity in surfaces[0].entities
        if entity.entity_type == "work_item"
        and entity.values.get("review_target_work_item_id") == target_work_item_id
        and entity.values.get("done") is False
    ]
    if len(matches) > 1:
        raise SoftwareIncUIValidationError("linked contract review work is ambiguous")
    return None if not matches else matches[0]


def _completed_review_work(
    snapshot: GameSnapshot, target_work_item_id: str
) -> ObservedEntity | None:
    review = _matching_review_work(snapshot, target_work_item_id)
    if review is None:
        return None
    progress = review.values.get("progress")
    stage = review.values.get("stage")
    if (
        isinstance(progress, (int, float))
        and not isinstance(progress, bool)
        and progress >= 1
        and isinstance(stage, str)
        and "reviews finished" in " ".join(stage.casefold().split())
    ):
        return review
    return None


def _single_number(snapshot: GameSnapshot, surface_name: str, field: str) -> Decimal | None:
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == surface_name
    ]
    if len(surfaces) != 1 or len(surfaces[0].entities) != 1:
        return None
    value = surfaces[0].entities[0].values.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def _entity_number(entity: ObservedEntity, field: str) -> Decimal:
    value = entity.values.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SoftwareIncUIVerificationError(f"completed contract field {field!r} is not numeric")
    return Decimal(str(value))


def _contract_ui_text(snapshot: GameSnapshot, field: str) -> str:
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == "contract_ui"
    ]
    if len(surfaces) != 1 or surfaces[0].coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
        raise SoftwareIncUIValidationError("contract UI state is incomplete")
    states = [
        entity for entity in surfaces[0].entities if entity.entity_type == "contract_ui_state"
    ]
    if len(states) != 1 or not isinstance(states[0].values.get(field), str):
        raise SoftwareIncUIValidationError(f"contract UI field {field!r} is unavailable")
    return str(states[0].values[field])


def _contract_ui_value(snapshot: GameSnapshot, field: str) -> object:
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == "contract_ui"
    ]
    if len(surfaces) != 1 or surfaces[0].coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
        raise SoftwareIncUIValidationError("contract UI state is incomplete")
    states = [
        entity for entity in surfaces[0].entities if entity.entity_type == "contract_ui_state"
    ]
    if len(states) != 1 or field not in states[0].values:
        raise SoftwareIncUIValidationError(f"contract UI field {field!r} is unavailable")
    return states[0].values[field]


def _review_cost(snapshot: GameSnapshot) -> Decimal:
    value = _contract_ui_value(snapshot, "review_cost_text")
    if not isinstance(value, str) or not value.strip():
        raise SoftwareIncUIValidationError("review cost is not visibly observed")
    normalized = value.replace("\u00a0", " ").strip()
    formula = re.fullmatch(
        r"Cost:\s*(\d[\d,]*)\s*x\s*\$\s*(-?\d[\d,]*(?:\.\d{1,2})?)"
        r"\s*=\s*\$\s*(-?\d[\d,]*(?:\.\d{1,2})?)",
        normalized,
        flags=re.IGNORECASE,
    )
    if formula is not None:
        count_token, unit_token, total_token = formula.groups()
        try:
            count = Decimal(count_token.replace(",", ""))
            unit = Decimal(unit_token.replace(",", ""))
            result = abs(Decimal(total_token.replace(",", "")))
        except InvalidOperation as error:
            raise SoftwareIncUIValidationError("review cost text is not valid USD") from error
        if abs(count * unit) != result:
            raise SoftwareIncUIValidationError("review cost formula total is inconsistent")
    else:
        tokens = re.findall(
            r"\$\s*(-?\d[\d,]*(?:\.\d{1,2})?)",
            normalized,
        )
        if len(tokens) != 1:
            raise SoftwareIncUIValidationError(
                f"review cost text {value!r} does not contain one exact USD total"
            )
        try:
            result = abs(Decimal(tokens[0].replace(",", "")))
        except InvalidOperation as error:
            raise SoftwareIncUIValidationError("review cost text is not valid USD") from error
    if not result.is_finite():
        raise SoftwareIncUIValidationError("review cost is not finite")
    return result.quantize(Decimal("0.01"))


def _review_configuration(snapshot: GameSnapshot) -> str:
    client = _contract_ui_value(snapshot, "review_client")
    internal = _contract_ui_value(snapshot, "review_internal")
    outsource = _contract_ui_value(snapshot, "review_outsource")
    count = _contract_ui_value(snapshot, "review_slider_value")
    if not all(isinstance(value, bool) for value in (client, internal, outsource)):
        raise SoftwareIncUIValidationError("review mode is not completely observed")
    if isinstance(count, bool) or not isinstance(count, (int, float)):
        raise SoftwareIncUIValidationError("review count is not observed")
    if bool(internal) == bool(outsource):
        raise SoftwareIncUIValidationError("review internal/outsource mode is ambiguous")
    mode = "client" if client else "outsource" if outsource else "internal"
    return f"mode={mode}, review_count={count:g}"


def _result(
    workflow: ContractWorkflow | None,
    gestures: int,
    verified: bool,
    partial: bool,
    message: str,
) -> ContractOperationResult:
    return ContractOperationResult(
        workflow=workflow,
        gestures_sent=gestures,
        verified=verified,
        partial=partial,
        message=message,
        completed_at=datetime.now(UTC),
    )


def _append_event(
    repository: ContractWorkflowStore,
    workflow: ContractWorkflow,
    *,
    event_type: str,
    bridge_sequence: int,
    stage_before: ContractStage,
    stage_after: ContractStage,
    action: str | None,
    input_sent: bool,
    verified: bool,
    detail: str,
) -> None:
    repository.append_event(
        ContractCycleEvent(
            event_id=uuid4(),
            workflow_id=workflow.workflow_id,
            sequence=len(repository.events(workflow.workflow_id)) + 1,
            event_type=event_type,
            bridge_sequence=bridge_sequence,
            stage_before=stage_before,
            stage_after=stage_after,
            action=action,
            input_sent=input_sent,
            verified=verified,
            detail=detail,
            recorded_at=datetime.now(UTC),
        )
    )


__all__ = [
    "accept_recommended_contract",
    "advance_contract",
    "browse_contracts",
    "promote_contract",
    "review_contract",
    "release_contract",
]
