"""Verified visible-UI operator for one Software Inc. education assignment."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from sim_pilot.computer_control.models import DesktopFrame, InputGesture, InputGestureKind
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
    TrainingApproval,
    TrainingCycleEvent,
    TrainingOperationResult,
    TrainingRecommendation,
    TrainingWorkflow,
    TrainingWorkflowStatus,
)
from .projection import current_cash, exact_employee_training
from .store import TrainingWorkflowStore
from .workflow import create_training_workflow, resolve_training_approval, synchronize_training

ApprovalProvider = Callable[[TrainingApproval], bool]


class TrainingInputBackend(Protocol):
    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> object: ...


class TrainingObserver(Protocol):
    @property
    def backend(self) -> TrainingInputBackend: ...

    async def observe(self) -> ObservedSoftwareIncUI: ...

    async def keep_game_foreground(self) -> None: ...


ObserverFactory = Callable[[], TrainingObserver]
_MAXIMUM_START_CYCLES = 20
_SETTLE_SECONDS = 0.1


async def start_training(
    recommendation: TrainingRecommendation | None,
    *,
    approval_provider: ApprovalProvider | None,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: TrainingWorkflowStore | None = None,
    existing_workflow: TrainingWorkflow | None = None,
) -> TrainingOperationResult:
    if existing_workflow is None and (recommendation is None or recommendation.recommended is None):
        raise SoftwareIncUIValidationError("there is no eligible employee to educate")
    repository = store or TrainingWorkflowStore()
    observer = observer_factory()
    current = await observer.observe()
    _require_actionable(current.observation)
    if existing_workflow is not None:
        workflow = existing_workflow
        _require_workflow_current(workflow, current.observation)
        approval = workflow.pending_approval
        if workflow.status is not TrainingWorkflowStatus.WAITING_FOR_APPROVAL or approval is None:
            raise SoftwareIncUIValidationError(
                "education workflow is not waiting for the next course approval"
            )
        refreshed_employee = exact_employee_training(
            current.observation.semantic_after,
            employee_id=workflow.employee_id,
            role="Designer",
            specialization="System",
        )
        if (
            refreshed_employee.level != approval.level_before
            or refreshed_employee.one_time_cost != approval.direct_cost
            or current_cash(current.observation.semantic_after) - approval.direct_cost
            < workflow.minimum_cash_reserve
        ):
            raise SoftwareIncUIValidationError(
                "next education course employee, level, cost, or reserve changed"
            )
    else:
        assert recommendation is not None and recommendation.recommended is not None
        candidate = recommendation.recommended
        _require_recommendation_current(recommendation, current.observation)
        refreshed_employee = exact_employee_training(
            current.observation.semantic_after,
            employee_id=candidate.employee.employee_id,
            role="Designer",
            specialization="System",
        )
        if (
            refreshed_employee.level != candidate.employee.level
            or refreshed_employee.one_time_cost != candidate.current_course_cost
            or current_cash(current.observation.semantic_after) - candidate.projected_direct_cost
            < candidate.minimum_cash_reserve
        ):
            raise SoftwareIncUIValidationError("education candidate, cost, or reserve changed")
        save_identity = recommendation.save_identity
        existing = repository.current(
            game_session_id=recommendation.game_session_id, save_identity=save_identity
        )
        if existing is not None:
            if (
                existing.employee_id != candidate.employee.employee_id
                or existing.plan_fingerprint
                != create_training_workflow(
                    current.observation.semantic_after, candidate
                ).plan_fingerprint
            ):
                raise SoftwareIncUIValidationError(
                    "another education workflow already owns this save"
                )
            workflow = existing
        else:
            workflow = create_training_workflow(current.observation.semantic_after, candidate)
            repository.save(workflow)

    observed = exact_employee_training(
        current.observation.semantic_after,
        employee_id=workflow.employee_id,
        role="Designer",
        specialization="System",
    )
    if any(course.casefold() == "designer:system" for course in observed.active_courses):
        return _result(
            workflow,
            0,
            True,
            False,
            f"{workflow.employee_name} is already in the approved Designer/System "
            "education; no input was sent.",
        )

    gestures = 0
    selecting: str | None = None
    for _ in range(_MAXIMUM_START_CYCLES):
        observation = current.observation
        _require_actionable(observation)
        scene = observation.scene
        effect: str
        if scene is SoftwareIncUIScene.GAMEPLAY_RUNNING:
            target = _target(observation, "pause_button")
            effect = "pause before education configuration"
        elif scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
            target = _target(observation, "open_employees")
            effect = "open visible employee management"
        elif scene is SoftwareIncUIScene.EMPLOYEE_MANAGEMENT:
            selected = _education_text(observation, "selected_employees", empty=True)
            if selected != workflow.employee_id:
                target = _target(observation, f"employee_row_{workflow.employee_id}")
                effect = f"select exact employee {workflow.employee_name!r}"
            else:
                target = _target(observation, "open_education")
                effect = "open the visible Education window"
        elif scene is SoftwareIncUIScene.EDUCATION:
            selected = _education_text(observation, "selected_employees", empty=True)
            selected_role = _education_text(observation, "selected_role", empty=True)
            selected_spec = _education_text(observation, "selected_specialization", empty=True)
            if selected != workflow.employee_id:
                target = _target(observation, f"education_employee_row_{workflow.employee_id}")
                effect = f"select exact education employee {workflow.employee_name!r}"
            elif selecting == "role" and selected_role.casefold() != "designer":
                target = _target(observation, "label:designer")
                effect = "select exact Designer education role"
                selecting = None
            elif selected_role.casefold() != "designer":
                target = _target(observation, "education_role_combo")
                effect = "open the education role choices"
                selecting = "role"
            elif selecting == "specialization" and selected_spec.casefold() != "system":
                target = _target(observation, "label:system")
                effect = "select exact System specialization"
                selecting = None
            elif selected_spec.casefold() != "system":
                target = _target(observation, "education_specialization_combo")
                effect = "open the education specialization choices"
                selecting = "specialization"
            else:
                observed_cost = _education_decimal(observation, "selected_cost")
                duration = _education_integer(observation, "duration_months")
                approval = workflow.pending_approval
                if approval is None:
                    raise SoftwareIncUIValidationError("education approval is unavailable")
                if observed_cost != approval.direct_cost or duration != 1:
                    raise SoftwareIncUIValidationError(
                        "visible education cost or duration differs from the approved plan"
                    )
                reusable = approval.approved is True
                if dry_run:
                    return _result(
                        workflow,
                        gestures,
                        False,
                        True,
                        f"Dry run: exact employee, Designer/System course "
                        f"{approval.stage_number} of 3, one month, and cost are visible; "
                        "the next step is exact approval.",
                    )
                if not reusable and approval_provider is None:
                    return _result(workflow, gestures, False, True, approval.action_summary)
                if not reusable:
                    assert approval_provider is not None
                    workflow = resolve_training_approval(
                        workflow, approved=approval_provider(approval)
                    )
                    repository.save(workflow)
                    if workflow.status is TrainingWorkflowStatus.BLOCKED:
                        return _result(
                            workflow,
                            gestures,
                            False,
                            False,
                            "Education spending was denied; no education commitment input was "
                            "sent.",
                        )
                refreshed = await observer.observe()
                _require_continuity(observation, refreshed.observation)
                _require_actionable(refreshed.observation)
                if (
                    refreshed.observation.scene is not SoftwareIncUIScene.EDUCATION
                    or _education_text(refreshed.observation, "selected_employees", empty=True)
                    != workflow.employee_id
                    or _education_text(
                        refreshed.observation, "selected_role", empty=True
                    ).casefold()
                    != "designer"
                    or _education_text(
                        refreshed.observation, "selected_specialization", empty=True
                    ).casefold()
                    != "system"
                    or _education_decimal(refreshed.observation, "selected_cost")
                    != approval.direct_cost
                ):
                    raise SoftwareIncUIValidationError(
                        "education identity or exact commitment changed while approval was pending"
                    )
                before_cash = current_cash(refreshed.observation.semantic_after)
                after = await _click(
                    observer,
                    refreshed,
                    _target(refreshed.observation, "commit_education"),
                    approval.action_summary,
                )
                gestures += 1
                trained = exact_employee_training(
                    after.observation.semantic_after,
                    employee_id=workflow.employee_id,
                    role="Designer",
                    specialization="System",
                )
                after_cash = current_cash(after.observation.semantic_after)
                if not any(
                    course.casefold() == "designer:system" for course in trained.active_courses
                ) or abs((before_cash - after_cash) - approval.direct_cost) > Decimal("0.02"):
                    raise SoftwareIncUIVerificationError(
                        "education commitment did not create the exact course and cash delta"
                    )
                workflow = workflow.model_copy(
                    update={
                        "actual_direct_cost": workflow.actual_direct_cost + approval.direct_cost
                    }
                )
                workflow = synchronize_training(workflow, after.observation.semantic_after)
                repository.save(workflow)
                _append_event(
                    repository,
                    workflow,
                    "education_started",
                    after.observation.semantic_after.bridge_sequence,
                    approval.action_summary,
                    True,
                    f"Designer:System active; cash ${before_cash:,.2f} -> ${after_cash:,.2f}",
                )
                return _result(
                    workflow,
                    gestures,
                    True,
                    False,
                    f"Started Designer/System course {approval.stage_number} of 3 for "
                    f"{workflow.employee_name}; exact ${approval.direct_cost:,.2f} cost and "
                    "active one-month course verified.",
                )
        else:
            raise SoftwareIncUIValidationError(
                f"education cannot continue from scene {scene.value}; close unrelated UI first"
            )
        if dry_run:
            return _result(workflow, gestures, False, True, f"Dry run: would {effect}.")
        current = await _click(observer, current, target, effect)
        gestures += 1
    raise SoftwareIncUIVerificationError("education setup exceeded the bounded cycle limit")


async def advance_training(
    workflow: TrainingWorkflow,
    *,
    run_seconds: float = 10.0,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: TrainingWorkflowStore | None = None,
) -> TrainingOperationResult:
    if not 0 < run_seconds <= 30:
        raise SoftwareIncUIValidationError(
            "education run interval must be between 0 and 30 seconds"
        )
    repository = store or TrainingWorkflowStore()
    observer = observer_factory()
    before = await observer.observe()
    _require_actionable(before.observation)
    current = synchronize_training(workflow, before.observation.semantic_after)
    if current.status is TrainingWorkflowStatus.COMPLETED:
        repository.save(current)
        return _result(
            current,
            0,
            True,
            False,
            "Education is complete; System specialization increased "
            f"{current.initial_level} -> {current.current_level}. No input was sent.",
        )
    if current.status is TrainingWorkflowStatus.WAITING_FOR_APPROVAL:
        repository.save(current)
        approval = current.pending_approval
        assert approval is not None
        return _result(
            current,
            0,
            True,
            True,
            f"Course {approval.stage_number - 1} of 3 is complete; System is level "
            f"{current.current_level}. Course {approval.stage_number} requires fresh exact "
            "approval; no input was sent.",
        )
    employee = exact_employee_training(
        before.observation.semantic_after,
        employee_id=current.employee_id,
        role="Designer",
        specialization="System",
    )
    if not any(course.casefold() == "designer:system" for course in employee.active_courses):
        raise SoftwareIncUIValidationError("the approved active education course is not observed")
    gestures = 0
    if before.observation.scene is not SoftwareIncUIScene.GAMEPLAY_PAUSED:
        if before.observation.paused:
            if dry_run:
                return _result(
                    current,
                    0,
                    False,
                    True,
                    "Dry run: would close the active management window with Escape.",
                )
            before = await _key(observer, before, "escape", "close reversible management UI")
            gestures += 1
        else:
            raise SoftwareIncUIValidationError(
                "education progression must begin from paused gameplay"
            )
    if before.observation.scene is not SoftwareIncUIScene.GAMEPLAY_PAUSED:
        raise SoftwareIncUIVerificationError("Escape did not return to paused gameplay")
    if dry_run:
        return _result(
            current,
            gestures,
            False,
            True,
            f"Dry run: would advance for {run_seconds:.1f} seconds and guarantee pause.",
        )
    running = await _click(
        observer,
        before,
        _target(before.observation, "resume_button"),
        "resume bounded education time",
    )
    gestures += 1
    if running.observation.paused:
        raise SoftwareIncUIVerificationError("education progression did not resume game time")
    try:
        await observer.keep_game_foreground()
        await asyncio.sleep(run_seconds)
    finally:
        # Once time has been resumed, cleanup owns the next runtime cycle even if
        # foregrounding, waiting, or cancellation interrupts the requested interval.
        # Shielding prevents a delivered cancellation from skipping the pause gesture.
        paused, pause_gestures = await asyncio.shield(_pause_after_bounded_interval(observer))
        gestures += pause_gestures
    updated = synchronize_training(current, paused.observation.semantic_after)
    repository.save(updated)
    complete = updated.status is TrainingWorkflowStatus.COMPLETED
    waiting = updated.status is TrainingWorkflowStatus.WAITING_FOR_APPROVAL
    event = _append_event(
        repository,
        updated,
        "education_completed"
        if complete
        else "education_course_completed"
        if waiting
        else "education_advanced",
        paused.observation.semantic_after.bridge_sequence,
        "bounded time progression",
        True,
        f"System level {updated.initial_level} -> {updated.current_level}; game paused=true",
    )
    return TrainingOperationResult(
        workflow=updated,
        event=event,
        gestures_sent=gestures,
        verified=True,
        partial=not complete,
        message=(
            "Education complete and paused; System specialization increased "
            f"{updated.initial_level} -> {updated.current_level}."
            if complete
            else (
                f"Course {updated.completed_courses} of 3 completed and game is paused; "
                f"System is level {updated.current_level}. The next course requires fresh "
                "exact approval."
                if waiting
                else f"Education remains active after {run_seconds:.1f}s; game is paused and "
                f"System remains level {updated.current_level}."
            )
        ),
        completed_at=datetime.now(UTC),
    )


async def _pause_after_bounded_interval(
    observer: TrainingObserver,
) -> tuple[ObservedSoftwareIncUI, int]:
    current = await observer.observe()
    _require_actionable(current.observation)
    if current.observation.paused:
        return current, 0
    paused = await _click(
        observer,
        current,
        _target(current.observation, "pause_button"),
        "pause after bounded education time",
    )
    if not paused.observation.paused:
        raise SoftwareIncUIVerificationError(
            "bounded education cleanup could not verify a paused game"
        )
    return paused, 1


async def _click(
    observer: TrainingObserver, before: ObservedSoftwareIncUI, target: VisualTarget, effect: str
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
    observer.backend.execute(gesture, frame=frame)  # type: ignore[arg-type]
    await asyncio.sleep(_SETTLE_SECONDS)
    after = await observer.observe()
    _require_continuity(before.observation, after.observation)
    return after


async def _key(
    observer: TrainingObserver, before: ObservedSoftwareIncUI, key: str, effect: str
) -> ObservedSoftwareIncUI:
    frame = before.observation.frame
    gesture = InputGesture(
        kind=InputGestureKind.KEY,
        key_code=53 if key == "escape" else None,
        expected_process_id=frame.process_id,
        expected_window_id=frame.window_id,
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene=before.observation.scene.value,
        target_id="escape_to_gameplay",
        intended_effect=effect,
    )
    observer.backend.execute(gesture, frame=frame)
    await asyncio.sleep(_SETTLE_SECONDS)
    after = await observer.observe()
    _require_continuity(before.observation, after.observation)
    return after


def _target(observation: SoftwareIncUIObservation, target_id: str) -> VisualTarget:
    matches = [target for target in observation.targets if target.target_id == target_id]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(
            f"fresh target {target_id!r} did not resolve exactly once"
        )
    target = matches[0]
    if (
        target.confidence < 0.8
        or target.source_frame_id != observation.frame.frame_id
        or target.expires_at <= datetime.now(UTC)
    ):
        raise SoftwareIncUIValidationError("education target is stale or ambiguous")
    return target


def _education_state(observation: SoftwareIncUIObservation):
    matches = [
        entity
        for surface in observation.semantic_after.surfaces
        if surface.coverage.surface == "education_ui"
        for entity in surface.entities
        if entity.entity_type == "education_ui_state" and entity.entity_id == "current"
    ]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError("education UI state is unavailable or ambiguous")
    return matches[0]


def _education_text(
    observation: SoftwareIncUIObservation, field: str, *, empty: bool = False
) -> str:
    value = _education_state(observation).values.get(field)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise SoftwareIncUIValidationError(f"education_ui.{field} is not observed text")
    return value


def _education_decimal(observation: SoftwareIncUIObservation, field: str) -> Decimal:
    value = _education_state(observation).values.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SoftwareIncUIValidationError(f"education_ui.{field} is not observed numeric")
    return Decimal(str(value))


def _education_integer(observation: SoftwareIncUIObservation, field: str) -> int:
    value = _education_state(observation).values.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"education_ui.{field} is not an integer")
    return value


def _require_recommendation_current(
    recommendation: TrainingRecommendation, observation: SoftwareIncUIObservation
) -> None:
    snapshot = observation.semantic_after
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    if recommendation.expires_at <= datetime.now(UTC):
        raise SoftwareIncUIValidationError("education recommendation expired")
    if (
        recommendation.game_session_id != snapshot.game_session_id
        or recommendation.save_identity != save_identity
    ):
        raise SoftwareIncUIValidationError(
            "education recommendation save or session identity is stale"
        )
    if snapshot.bridge_sequence <= recommendation.source_bridge_sequence:
        raise SoftwareIncUIValidationError("education start requires a fresh bridge sequence")


def _require_workflow_current(
    workflow: TrainingWorkflow, observation: SoftwareIncUIObservation
) -> None:
    snapshot = observation.semantic_after
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    if (
        workflow.game_session_id != snapshot.game_session_id
        or workflow.save_identity != save_identity
    ):
        raise SoftwareIncUIValidationError("education workflow save or session identity is stale")
    if snapshot.bridge_sequence <= workflow.last_bridge_sequence:
        raise SoftwareIncUIValidationError(
            "education continuation requires a fresh bridge sequence"
        )


def _require_actionable(observation: SoftwareIncUIObservation) -> None:
    if observation.modal_state is not ModalState.NONE:
        raise SoftwareIncUIObservationError(
            f"cannot operate education while modal state is {observation.modal_state.value}"
        )
    if observation.scene in {SoftwareIncUIScene.UNKNOWN, SoftwareIncUIScene.BLOCKING_MODAL}:
        raise SoftwareIncUIObservationError(
            f"cannot operate education from {observation.scene.value}"
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


def _append_event(
    repository: TrainingWorkflowStore,
    workflow: TrainingWorkflow,
    event_type: str,
    bridge_sequence: int,
    action: str | None,
    input_sent: bool,
    detail: str,
) -> TrainingCycleEvent:
    event = TrainingCycleEvent(
        event_id=uuid4(),
        workflow_id=workflow.workflow_id,
        sequence=len(repository.events(workflow.workflow_id)) + 1,
        event_type=event_type,
        bridge_sequence=bridge_sequence,
        action=action,
        input_sent=input_sent,
        verified=True,
        detail=detail,
        recorded_at=datetime.now(UTC),
    )
    repository.append_event(event)
    return event


def _result(
    workflow: TrainingWorkflow | None,
    gestures: int,
    verified: bool,
    partial: bool,
    message: str,
) -> TrainingOperationResult:
    return TrainingOperationResult(
        workflow=workflow,
        gestures_sent=gestures,
        verified=verified,
        partial=partial,
        message=message,
        completed_at=datetime.now(UTC),
    )


__all__ = ["advance_training", "start_training"]
