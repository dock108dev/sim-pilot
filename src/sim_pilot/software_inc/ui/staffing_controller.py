"""Approval-gated, one-gesture staffing workflows through Software Inc.'s visible UI."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sim_pilot.computer_control.models import InputGesture, InputGestureKind
from sim_pilot.game_bridge.models import GameSnapshot, JsonValue
from sim_pilot.software_inc.errors import (
    SoftwareIncUIObservationError,
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)

from .models import (
    ApplicantObservation,
    ModalState,
    SoftwareIncUIAction,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    StaffingApproval,
    StaffingApprovalStatus,
    StaffingIntent,
    StaffingPlan,
    StaffingResult,
    StaffingTraceRecord,
    VisualTarget,
)
from .observer import ObservedSoftwareIncUI, SoftwareIncUIObserver
from .staffing import (
    applicant_observations,
    build_staffing_plan,
    normalize_team_name,
    pending_approval,
    require_team_absent,
    require_unique_team,
    require_valid_approval,
    resolve_approval,
    select_applicant,
    verify_applicant_search,
    verify_employee_hired,
    verify_team_created,
)
from .trace import append_staffing_trace

ApprovalProvider = Callable[[StaffingPlan, StaffingApproval], bool]
ObserverFactory = Callable[[], SoftwareIncUIObserver]
TraceWriter = Callable[[StaffingTraceRecord], object]
_MAXIMUM_CYCLES = 24


async def execute_staffing_intent(
    intent: StaffingIntent,
    *,
    dry_run: bool = False,
    approval_provider: ApprovalProvider | None = None,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    trace_writer: TraceWriter = append_staffing_trace,
) -> StaffingResult:
    """Run a bounded staffing state machine with one fresh-frame gesture per cycle."""
    observer = observer_factory()
    initial = await observer.observe()
    current = initial
    operation_id = uuid4()
    gestures = 0
    cycle = 1
    last_plan: StaffingPlan | None = None
    last_approval: StaffingApproval | None = None
    search_verified = False
    selected: ApplicantObservation | None = None

    if intent.action is SoftwareIncUIAction.CREATE_TEAM:
        require_team_absent(current.observation.semantic_after, intent.team_name)
    else:
        require_unique_team(current.observation.semantic_after, intent.team_name)

    while cycle <= _MAXIMUM_CYCLES:
        _require_actionable(current.observation)
        observation = current.observation
        scene = observation.scene

        if scene is SoftwareIncUIScene.GAMEPLAY_RUNNING:
            result = await _gesture_cycle(
                operation_id,
                intent.action,
                cycle,
                current,
                observer=observer,
                target_id="pause_button",
                effect="pause before staffing navigation",
                dry_run=dry_run,
                trace_writer=trace_writer,
            )
            if dry_run:
                return _result(
                    intent,
                    initial.observation,
                    result.observation,
                    gestures,
                    cycle,
                    True,
                    "Dry run: the next bounded cycle would pause the game.",
                )
            current = result
            gestures += 1
            cycle += 1
            continue

        if scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
            result = await _gesture_cycle(
                operation_id,
                intent.action,
                cycle,
                current,
                observer=observer,
                target_id="manage_teams_button",
                effect="open Manage Teams for the staffing workflow",
                dry_run=dry_run,
                trace_writer=trace_writer,
            )
            if dry_run:
                return _result(
                    intent,
                    initial.observation,
                    result.observation,
                    gestures,
                    cycle,
                    True,
                    "Dry run: the next bounded cycle would open Manage Teams.",
                )
            if result.observation.scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
                raise SoftwareIncUIVerificationError(
                    "Manage Teams click produced a fresh observation but did not open the "
                    "window; no retry attempted"
                )
            current = result
            gestures += 1
            cycle += 1
            continue

        if intent.action is SoftwareIncUIAction.CREATE_TEAM:
            if scene is SoftwareIncUIScene.MANAGE_TEAMS:
                result = await _gesture_cycle(
                    operation_id,
                    intent.action,
                    cycle,
                    current,
                    observer=observer,
                    target_id="open_create_team",
                    effect="open the visible new-team form",
                    dry_run=dry_run,
                    trace_writer=trace_writer,
                )
                if dry_run:
                    return _result(
                        intent,
                        initial.observation,
                        result.observation,
                        gestures,
                        cycle,
                        True,
                        "Dry run: the next bounded cycle would open the new-team form.",
                    )
                current = result
                gestures += 1
                cycle += 1
                continue
            if scene is SoftwareIncUIScene.CREATE_TEAM_FORM:
                team_value = _staffing_text(
                    observation.semantic_after,
                    "team_name_value",
                    allow_empty=True,
                )
                if team_value != intent.team_name:
                    if team_value:
                        raise SoftwareIncUIValidationError(
                            "new-team field is not empty; refusing to overwrite visible text"
                        )
                    if not _input_focused(observation):
                        result = await _gesture_cycle(
                            operation_id,
                            intent.action,
                            cycle,
                            current,
                            observer=observer,
                            target_id="team_name_input",
                            effect="focus the empty new-team name field",
                            dry_run=dry_run,
                            trace_writer=trace_writer,
                        )
                        if dry_run:
                            return _result(
                                intent,
                                initial.observation,
                                result.observation,
                                gestures,
                                cycle,
                                True,
                                "Dry run: the next bounded cycle would focus the empty "
                                "team-name field.",
                            )
                        if not _input_focused(result.observation):
                            raise SoftwareIncUIVerificationError(
                                "team-name click produced a fresh observation but did not focus "
                                "the field; no retry attempted"
                            )
                        current = result
                        gestures += 1
                        cycle += 1
                        continue
                    result = await _text_cycle(
                        operation_id,
                        intent.action,
                        cycle,
                        current,
                        observer=observer,
                        text=intent.team_name,
                        effect="enter the requested team name",
                        dry_run=dry_run,
                        trace_writer=trace_writer,
                    )
                    if dry_run:
                        return _result(
                            intent,
                            initial.observation,
                            result.observation,
                            gestures,
                            cycle,
                            True,
                            f"Dry run: the next bounded cycle would type {intent.team_name!r}.",
                        )
                    current = result
                    gestures += 1
                    cycle += 1
                    continue
                last_plan = build_staffing_plan(intent, observation)
                last_approval = pending_approval(last_plan)
                approved = _approval_decision(
                    last_plan,
                    last_approval,
                    dry_run=dry_run,
                    provider=approval_provider,
                )
                if dry_run or not approved:
                    if not dry_run:
                        last_approval = resolve_approval(last_approval, approved=False)
                    return _approval_result(
                        intent,
                        initial.observation,
                        observation,
                        last_plan,
                        last_approval,
                        gestures,
                        cycle,
                        dry_run=dry_run,
                    )
                last_approval = resolve_approval(last_approval, approved=True)
                current = await observer.observe()
                require_valid_approval(last_plan, last_approval, current.observation)
                semantic_before = current.observation.semantic_after
                current = await _gesture_cycle(
                    operation_id,
                    intent.action,
                    cycle,
                    current,
                    observer=observer,
                    target_id="commit_create_team",
                    effect=f"create exactly one team named {intent.team_name}",
                    dry_run=False,
                    trace_writer=trace_writer,
                    approval=last_approval,
                    plan=last_plan,
                )
                gestures += 1
                verify_team_created(
                    semantic_before,
                    current.observation.semantic_after,
                    team_name=intent.team_name,
                )
                return _result(
                    intent,
                    initial.observation,
                    current.observation,
                    gestures,
                    cycle,
                    False,
                    f"Created team {intent.team_name!r}; exact team delta verified.",
                    plan=last_plan,
                    approval=last_approval,
                    expected=last_plan.expected_differences,
                )
            raise SoftwareIncUIObservationError(
                f"team creation cannot continue from scene {scene.value}"
            )

        if scene in {SoftwareIncUIScene.MANAGE_TEAMS, SoftwareIncUIScene.CREATE_TEAM_FORM}:
            result = await _gesture_cycle(
                operation_id,
                intent.action,
                cycle,
                current,
                observer=observer,
                target_id="open_hiring",
                effect="open the visible hiring setup",
                dry_run=dry_run,
                trace_writer=trace_writer,
            )
            if dry_run:
                return _result(
                    intent,
                    initial.observation,
                    result.observation,
                    gestures,
                    cycle,
                    True,
                    "Dry run: the next bounded cycle would open hiring.",
                )
            if result.observation.scene in {
                SoftwareIncUIScene.MANAGE_TEAMS,
                SoftwareIncUIScene.CREATE_TEAM_FORM,
            }:
                raise SoftwareIncUIVerificationError(
                    "Hire employees click produced a fresh observation but did not open hiring; "
                    "no retry attempted"
                )
            current = result
            gestures += 1
            cycle += 1
            continue

        if scene is SoftwareIncUIScene.HIRING_SETUP:
            role = _staffing_text(
                observation.semantic_after,
                "role",
                allow_empty=True,
            )
            wage = _staffing_text(
                observation.semantic_after,
                "wage_bracket",
                allow_empty=True,
            )
            if role.casefold() != "programmer":
                target_id = (
                    "label:programmer"
                    if _has_target(observation, "label:programmer")
                    else "role_combo"
                )
                current = await _gesture_cycle(
                    operation_id,
                    intent.action,
                    cycle,
                    current,
                    observer=observer,
                    target_id=target_id,
                    effect="select Programmer as the primary hiring role",
                    dry_run=dry_run,
                    trace_writer=trace_writer,
                )
                if dry_run:
                    return _result(
                        intent,
                        initial.observation,
                        current.observation,
                        gestures,
                        cycle,
                        True,
                        f"Dry run: the next bounded cycle would click {target_id}.",
                    )
                observed_role = _staffing_text(
                    current.observation.semantic_after,
                    "role",
                    allow_empty=True,
                )
                if observed_role.casefold() != "programmer" and not _has_target(
                    current.observation, "label:programmer"
                ):
                    raise SoftwareIncUIVerificationError(
                        "role selection click produced a fresh observation but neither selected "
                        "Programmer nor opened its visible option; no retry attempted"
                    )
                gestures += 1
                cycle += 1
                continue
            if wage.casefold() != "low":
                target_id = "label:low" if _has_target(observation, "label:low") else "wage_combo"
                current = await _gesture_cycle(
                    operation_id,
                    intent.action,
                    cycle,
                    current,
                    observer=observer,
                    target_id=target_id,
                    effect="select the Low wage bracket before applying the exact salary cap",
                    dry_run=dry_run,
                    trace_writer=trace_writer,
                )
                if dry_run:
                    return _result(
                        intent,
                        initial.observation,
                        current.observation,
                        gestures,
                        cycle,
                        True,
                        f"Dry run: the next bounded cycle would click {target_id}.",
                    )
                observed_wage = _staffing_text(
                    current.observation.semantic_after,
                    "wage_bracket",
                    allow_empty=True,
                )
                if observed_wage.casefold() != "low" and not _has_target(
                    current.observation, "label:low"
                ):
                    raise SoftwareIncUIVerificationError(
                        "wage selection click produced a fresh observation but neither selected "
                        "Low nor opened its visible option; no retry attempted"
                    )
                gestures += 1
                cycle += 1
                continue
            search_intent = intent.model_copy(
                update={"action": SoftwareIncUIAction.OBSERVE_APPLICANTS}
            )
            last_plan = build_staffing_plan(search_intent, observation)
            last_approval = pending_approval(last_plan)
            approved = _approval_decision(
                last_plan,
                last_approval,
                dry_run=dry_run,
                provider=approval_provider,
            )
            if dry_run or not approved:
                if not dry_run:
                    last_approval = resolve_approval(last_approval, approved=False)
                return _approval_result(
                    intent,
                    initial.observation,
                    observation,
                    last_plan,
                    last_approval,
                    gestures,
                    cycle,
                    dry_run=dry_run,
                )
            last_approval = resolve_approval(last_approval, approved=True)
            current = await observer.observe()
            require_valid_approval(last_plan, last_approval, current.observation)
            semantic_before = current.observation.semantic_after
            current = await _gesture_cycle(
                operation_id,
                intent.action,
                cycle,
                current,
                observer=observer,
                target_id="begin_applicant_search",
                effect="purchase the exact approved applicant search",
                dry_run=False,
                trace_writer=trace_writer,
                approval=last_approval,
                plan=last_plan,
            )
            gestures += 1
            cycle += 1
            verify_applicant_search(
                semantic_before,
                current.observation.semantic_after,
                plan=last_plan,
            )
            search_verified = True
            if intent.action is SoftwareIncUIAction.OBSERVE_APPLICANTS:
                candidates = applicant_observations(current.observation.semantic_after)
                return _result(
                    intent,
                    initial.observation,
                    current.observation,
                    gestures,
                    cycle - 1,
                    False,
                    f"Observed {len(candidates)} applicants after the approved search charge.",
                    plan=last_plan,
                    approval=last_approval,
                    expected=last_plan.expected_differences,
                )
            continue

        if scene is SoftwareIncUIScene.APPLICANT_LIST:
            if intent.role is None or intent.maximum_monthly_salary is None:
                raise SoftwareIncUIValidationError("hire intent lost its role or salary limit")
            selected = selected or select_applicant(
                observation.semantic_after,
                team_name=intent.team_name,
                role=intent.role,
                maximum_monthly_salary=intent.maximum_monthly_salary,
            )
            selected_team = _staffing_text(
                observation.semantic_after, "selected_team", allow_empty=True
            )
            if normalize_team_name(selected_team) != normalize_team_name(intent.team_name):
                team_target = f"label:{normalize_team_name(intent.team_name)}"
                target_id = team_target if _has_target(observation, team_target) else "choose_team"
                current = await _gesture_cycle(
                    operation_id,
                    intent.action,
                    cycle,
                    current,
                    observer=observer,
                    target_id=target_id,
                    effect=f"assign the hire to team {intent.team_name}",
                    dry_run=dry_run,
                    trace_writer=trace_writer,
                )
                if dry_run:
                    return _result(
                        intent,
                        initial.observation,
                        current.observation,
                        gestures,
                        cycle,
                        True,
                        f"Dry run: the next bounded cycle would click {target_id}.",
                    )
                gestures += 1
                cycle += 1
                continue
            selected_indexes = _staffing_text(
                observation.semantic_after,
                "selected_applicant_indices",
                allow_empty=True,
            ).split(",")
            if str(selected.display_index) not in selected_indexes:
                current = await _gesture_cycle(
                    operation_id,
                    intent.action,
                    cycle,
                    current,
                    observer=observer,
                    target_id=f"applicant_row_{selected.display_index}",
                    effect=f"select applicant {selected.name} at ${selected.salary:,.2f}/month",
                    dry_run=dry_run,
                    trace_writer=trace_writer,
                )
                if dry_run:
                    return _result(
                        intent,
                        initial.observation,
                        current.observation,
                        gestures,
                        cycle,
                        True,
                        f"Dry run: the next bounded cycle would select applicant {selected.name}.",
                    )
                gestures += 1
                cycle += 1
                continue
            last_plan = build_staffing_plan(intent, observation, applicant=selected)
            last_approval = pending_approval(last_plan)
            approved = _approval_decision(
                last_plan,
                last_approval,
                dry_run=dry_run,
                provider=approval_provider,
            )
            if dry_run or not approved:
                if not dry_run:
                    last_approval = resolve_approval(last_approval, approved=False)
                return _approval_result(
                    intent,
                    initial.observation,
                    observation,
                    last_plan,
                    last_approval,
                    gestures,
                    cycle,
                    dry_run=dry_run,
                )
            last_approval = resolve_approval(last_approval, approved=True)
            current = await observer.observe()
            require_valid_approval(last_plan, last_approval, current.observation)
            semantic_before = current.observation.semantic_after
            current = await _gesture_cycle(
                operation_id,
                intent.action,
                cycle,
                current,
                observer=observer,
                target_id="commit_hire",
                effect=(
                    f"hire {selected.name} into {intent.team_name} "
                    f"for ${selected.salary:,.2f}/month"
                ),
                dry_run=False,
                trace_writer=trace_writer,
                approval=last_approval,
                plan=last_plan,
            )
            gestures += 1
            verify_employee_hired(
                semantic_before,
                current.observation.semantic_after,
                plan=last_plan,
            )
            prefix = "Paid search and " if search_verified else ""
            return _result(
                intent,
                initial.observation,
                current.observation,
                gestures,
                cycle,
                False,
                (
                    f"{prefix}hired {selected.name} into {intent.team_name} for "
                    f"${selected.salary:,.2f}/month; recurring payroll verified."
                ),
                plan=last_plan,
                approval=last_approval,
                expected=last_plan.expected_differences,
            )

        raise SoftwareIncUIObservationError(
            f"staffing workflow cannot continue from scene {scene.value}"
        )

    raise SoftwareIncUIVerificationError(
        f"staffing workflow exceeded {_MAXIMUM_CYCLES} bounded cycles"
    )


async def _gesture_cycle(
    operation_id: UUID,
    action: SoftwareIncUIAction,
    cycle: int,
    current: ObservedSoftwareIncUI,
    *,
    observer: SoftwareIncUIObserver,
    target_id: str,
    effect: str,
    dry_run: bool,
    trace_writer: TraceWriter,
    plan: StaffingPlan | None = None,
    approval: StaffingApproval | None = None,
) -> ObservedSoftwareIncUI:
    target = _target(current.observation, target_id)
    gesture = _click_gesture(current.observation, target, effect=effect)
    if dry_run:
        _trace(
            trace_writer,
            operation_id,
            action,
            cycle,
            current.observation,
            target_id,
            gesture,
            False,
            True,
            "dry run validated exactly one current-frame click",
            plan=plan,
            approval=approval,
        )
        return current
    observer.backend.execute(gesture, frame=current.observation.frame)
    try:
        after = await observer.observe()
    except Exception as error:
        _trace(
            trace_writer,
            operation_id,
            action,
            cycle,
            current.observation,
            target_id,
            gesture,
            True,
            False,
            "input was sent but fresh verification failed; no retry attempted",
            plan=plan,
            approval=approval,
        )
        raise SoftwareIncUIVerificationError(
            f"gesture for {target_id!r} was sent but could not be verified; no retry attempted"
        ) from error
    _require_identity_continuity(current.observation, after.observation)
    _trace(
        trace_writer,
        operation_id,
        action,
        cycle,
        after.observation,
        target_id,
        gesture,
        True,
        True,
        "fresh screenshot and semantic snapshot observed after one gesture",
        plan=plan,
        approval=approval,
    )
    return after


async def _text_cycle(
    operation_id: UUID,
    action: SoftwareIncUIAction,
    cycle: int,
    current: ObservedSoftwareIncUI,
    *,
    observer: SoftwareIncUIObserver,
    text: str,
    effect: str,
    dry_run: bool,
    trace_writer: TraceWriter,
) -> ObservedSoftwareIncUI:
    frame = current.observation.frame
    gesture = InputGesture(
        kind=InputGestureKind.TEXT,
        text=text,
        expected_process_id=frame.process_id,
        expected_window_id=frame.window_id,
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene=current.observation.scene.value,
        target_id="team_name_input",
        intended_effect=effect,
    )
    if dry_run:
        _trace(
            trace_writer,
            operation_id,
            action,
            cycle,
            current.observation,
            "team_name_input",
            gesture,
            False,
            True,
            "dry run validated exactly one bounded Unicode text gesture",
        )
        return current
    observer.backend.execute(gesture, frame=frame)
    after = await observer.observe()
    _require_identity_continuity(current.observation, after.observation)
    if _staffing_text(after.observation.semantic_after, "team_name_value") != text:
        raise SoftwareIncUIVerificationError(
            "team-name text input was sent but exact visible field value was not observed"
        )
    _trace(
        trace_writer,
        operation_id,
        action,
        cycle,
        after.observation,
        "team_name_input",
        gesture,
        True,
        True,
        "exact visible team-name field value verified after one text gesture",
    )
    return after


def _approval_decision(
    plan: StaffingPlan,
    approval: StaffingApproval,
    *,
    dry_run: bool,
    provider: ApprovalProvider | None,
) -> bool:
    if dry_run:
        return False
    if provider is None:
        raise SoftwareIncUIValidationError(
            "staffing commitment requires an explicit approval provider"
        )
    return provider(plan, approval)


def _approval_result(
    intent: StaffingIntent,
    before: SoftwareIncUIObservation,
    after: SoftwareIncUIObservation,
    plan: StaffingPlan,
    approval: StaffingApproval,
    gestures: int,
    cycles: int,
    *,
    dry_run: bool,
) -> StaffingResult:
    if plan.action is SoftwareIncUIAction.OBSERVE_APPLICANTS:
        cost = f"one-time applicant-search charge ${plan.expected_one_time_cost:,.2f}"
    elif plan.action is SoftwareIncUIAction.HIRE_EMPLOYEE:
        assert plan.applicant is not None
        cost = (
            f"{plan.applicant.name} at ${plan.expected_monthly_cost:,.2f}/month "
            f"(cap ${plan.maximum_monthly_salary:,.2f})"
        )
    else:
        cost = f"team creation for {plan.team_name!r}"
    prefix = "Dry run reached" if dry_run else "Approval denied at"
    return _result(
        intent,
        before,
        after,
        gestures,
        cycles,
        dry_run,
        f"{prefix} the exact {cost}; no commitment click was sent.",
        plan=plan,
        approval=approval,
        partial=not dry_run,
    )


def _staffing_state(snapshot: GameSnapshot) -> dict[str, JsonValue]:
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == "staffing_ui"
    ]
    if len(surfaces) != 1:
        raise SoftwareIncUIObservationError("staffing_ui surface did not resolve exactly once")
    states = [
        entity
        for entity in surfaces[0].entities
        if entity.entity_type == "staffing_ui_state" and entity.entity_id == "current"
    ]
    if len(states) != 1:
        raise SoftwareIncUIObservationError("staffing UI state did not resolve exactly once")
    return states[0].values


def _staffing_text(
    snapshot: GameSnapshot,
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = _staffing_state(snapshot).get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SoftwareIncUIObservationError(f"staffing UI field {key!r} is unavailable")
    return value


def _input_focused(observation: SoftwareIncUIObservation) -> bool:
    value = _staffing_state(observation.semantic_after).get("team_name_focused")
    if not isinstance(value, bool):
        raise SoftwareIncUIObservationError("team-name input focus is unavailable")
    return value


def _has_target(observation: SoftwareIncUIObservation, target_id: str) -> bool:
    return sum(target.target_id == target_id for target in observation.targets) == 1


def _target(observation: SoftwareIncUIObservation, target_id: str) -> VisualTarget:
    matches = [target for target in observation.targets if target.target_id == target_id]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(
            f"target {target_id!r} did not resolve exactly once in the fresh frame"
        )
    target = matches[0]
    if (
        target.point is None
        or target.confidence < 0.8
        or target.source_frame_id != observation.frame.frame_id
        or target.scene is not observation.scene
        or target.projection_id != observation.projection_id
        or target.expires_at <= datetime.now(UTC)
    ):
        raise SoftwareIncUIValidationError(f"target {target_id!r} is ambiguous, stale, or unbound")
    return target


def _click_gesture(
    observation: SoftwareIncUIObservation,
    target: VisualTarget,
    *,
    effect: str,
) -> InputGesture:
    assert target.point is not None
    frame = observation.frame
    return InputGesture(
        kind=InputGestureKind.CLICK,
        point=target.point,
        expected_process_id=frame.process_id,
        expected_window_id=frame.window_id,
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene=observation.scene.value,
        target_id=target.target_id,
        intended_effect=effect,
    )


def _require_actionable(observation: SoftwareIncUIObservation) -> None:
    if observation.modal_state is not ModalState.NONE:
        raise SoftwareIncUIObservationError(
            f"cannot act while modal state is {observation.modal_state.value}"
        )
    if observation.scene in {
        SoftwareIncUIScene.UNKNOWN,
        SoftwareIncUIScene.BLOCKING_MODAL,
        SoftwareIncUIScene.HIRING_CONFIRMATION,
    }:
        raise SoftwareIncUIObservationError(
            f"cannot act from unproven scene {observation.scene.value}"
        )


def _require_identity_continuity(
    before: SoftwareIncUIObservation,
    after: SoftwareIncUIObservation,
) -> None:
    left = before.semantic_after
    right = after.semantic_after
    if (
        left.bridge_instance_id != right.bridge_instance_id
        or left.game_session_id != right.game_session_id
        or left.save_identity != right.save_identity
        or right.bridge_sequence <= left.bridge_sequence
        or before.frame.process_id != after.frame.process_id
        or before.frame.window_id != after.frame.window_id
        or before.frame.window_bounds != after.frame.window_bounds
    ):
        raise SoftwareIncUIVerificationError(
            "bridge, save, process, or window identity changed during staffing"
        )


def _trace(
    writer: TraceWriter,
    operation_id: UUID,
    action: SoftwareIncUIAction,
    cycle: int,
    observation: SoftwareIncUIObservation,
    target_id: str | None,
    gesture: InputGesture | None,
    input_sent: bool,
    verified: bool,
    reason: str,
    *,
    plan: StaffingPlan | None = None,
    approval: StaffingApproval | None = None,
) -> None:
    writer(
        StaffingTraceRecord(
            operation_id=operation_id,
            action=action,
            cycle=cycle,
            plan_fingerprint=None if plan is None else plan.fingerprint,
            approval_id=None if approval is None else approval.id,
            observation_frame_id=observation.frame.frame_id,
            bridge_sequence=observation.semantic_after.bridge_sequence,
            scene=observation.scene,
            projection_id=observation.projection_id,
            target_id=target_id,
            gesture=gesture,
            input_sent=input_sent,
            verified=verified,
            reason=reason,
            recorded_at=datetime.now(UTC),
        )
    )


def _result(
    intent: StaffingIntent,
    before: SoftwareIncUIObservation,
    after: SoftwareIncUIObservation,
    gestures: int,
    cycles: int,
    dry_run: bool,
    message: str,
    *,
    plan: StaffingPlan | None = None,
    approval: StaffingApproval | None = None,
    expected: tuple[str, ...] = (),
    partial: bool = False,
) -> StaffingResult:
    verified = (
        approval is None
        or approval.status in {StaffingApprovalStatus.APPROVED, StaffingApprovalStatus.DENIED}
        or dry_run
    )
    return StaffingResult(
        intent=intent,
        plan=plan,
        approval=approval,
        before=before,
        after=after,
        gestures_sent=gestures,
        cycles=cycles,
        dry_run=dry_run,
        verified=verified,
        partial=partial,
        expected_differences=expected,
        message=message,
        completed_at=datetime.now(UTC),
    )


__all__ = ["ApprovalProvider", "execute_staffing_intent"]
