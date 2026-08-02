"""One-gesture-per-cycle schedule and role control through Software Inc.'s visible UI."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sim_pilot.computer_control.models import InputGesture, InputGestureKind, KeyModifier
from sim_pilot.game_bridge import GameSnapshot
from sim_pilot.software_inc.errors import (
    SoftwareIncUIObservationError,
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)

from .models import (
    ModalState,
    SoftwareIncUIAction,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    StaffingTraceRecord,
    VisualTarget,
)
from .observer import ObservedSoftwareIncUI, SoftwareIncUIObserver
from .office import (
    OfficeIntent,
    OfficeOperationResult,
    SupportedEmployeeRole,
    project_team_readiness,
    require_unique_employee,
    verify_employee_role,
    verify_working_hours,
)
from .trace import append_staffing_trace

ObserverFactory = Callable[[], SoftwareIncUIObserver]
TraceWriter = Callable[[StaffingTraceRecord], object]
_MAXIMUM_CYCLES = 20
_ROLE_INDEX = {
    SupportedEmployeeRole.LEAD: 0,
    SupportedEmployeeRole.PROGRAMMER: 1,
    SupportedEmployeeRole.DESIGNER: 2,
    SupportedEmployeeRole.ARTIST: 3,
    SupportedEmployeeRole.SERVICE: 4,
}


async def execute_office_intent(
    intent: OfficeIntent,
    *,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    trace_writer: TraceWriter = append_staffing_trace,
) -> OfficeOperationResult:
    """Execute one bounded schedule/role workflow with fresh verification per gesture."""
    observer = observer_factory()
    initial = await observer.observe()
    current = initial
    operation_id = uuid4()
    gestures = 0
    cycle = 1
    selected_field: str | None = None

    project_team_readiness(initial.observation.semantic_after, intent.team_name)
    if intent.action is SoftwareIncUIAction.SET_TEAM_WORKING_HOURS and _semantic_hours_match(
        initial.observation.semantic_after, intent
    ):
        verify_working_hours(
            initial.observation.semantic_after,
            initial.observation.semantic_after,
            intent,
        )
        return _result(
            intent,
            initial.observation,
            initial.observation,
            gestures=0,
            cycles=1,
            dry_run=dry_run,
            verified=True,
            message=(
                f"{intent.team_name} already has the requested working hours; no input was sent."
            ),
        )
    employee_id: str | None = None
    if intent.action is SoftwareIncUIAction.ASSIGN_EMPLOYEE_ROLE:
        assert intent.employee_name is not None
        employee_id = require_unique_employee(
            initial.observation.semantic_after, intent.employee_name, intent.team_name
        ).entity_id
        if _employee_has_role(initial.observation.semantic_after, employee_id, intent):
            assert intent.role is not None
            return _result(
                intent,
                initial.observation,
                initial.observation,
                gestures=0,
                cycles=1,
                dry_run=dry_run,
                verified=True,
                message=(
                    f"{intent.employee_name} already has the observed {intent.role.value} role; "
                    "no input was sent."
                ),
            )

    while cycle <= _MAXIMUM_CYCLES:
        observation = current.observation
        _require_actionable(observation)
        scene = observation.scene

        if scene is SoftwareIncUIScene.GAMEPLAY_RUNNING:
            current = await _send(
                observer,
                current,
                _click(
                    observation,
                    _target(observation, "pause_button"),
                    "pause before office configuration",
                ),
                intent=intent,
                cycle=cycle,
                operation_id=operation_id,
                dry_run=dry_run,
                trace_writer=trace_writer,
            )
            if dry_run:
                return _dry_result(
                    intent,
                    initial.observation,
                    current.observation,
                    gestures,
                    cycle,
                    "pause the game",
                )
            gestures += 1
            cycle += 1
            continue

        if scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
            current = await _send(
                observer,
                current,
                _click(
                    observation, _target(observation, "manage_teams_button"), "open Manage Teams"
                ),
                intent=intent,
                cycle=cycle,
                operation_id=operation_id,
                dry_run=dry_run,
                trace_writer=trace_writer,
            )
            if dry_run:
                return _dry_result(
                    intent,
                    initial.observation,
                    current.observation,
                    gestures,
                    cycle,
                    "open Manage Teams",
                )
            gestures += 1
            cycle += 1
            continue

        if scene is SoftwareIncUIScene.MANAGE_TEAMS:
            selected_teams = _office_text(observation.semantic_after, "selected_teams", empty=True)
            if selected_teams.casefold() != intent.team_name.casefold():
                current = await _send(
                    observer,
                    current,
                    _click(
                        observation,
                        _target(observation, f"team_row_{intent.team_name}"),
                        f"select the exact team {intent.team_name}",
                    ),
                    intent=intent,
                    cycle=cycle,
                    operation_id=operation_id,
                    dry_run=dry_run,
                    trace_writer=trace_writer,
                )
                if dry_run:
                    return _dry_result(
                        intent,
                        initial.observation,
                        current.observation,
                        gestures,
                        cycle,
                        f"select {intent.team_name}",
                    )
                if (
                    _office_text(
                        current.observation.semantic_after, "selected_teams", empty=True
                    ).casefold()
                    != intent.team_name.casefold()
                ):
                    raise SoftwareIncUIVerificationError(
                        "the requested team was not uniquely selected"
                    )
                gestures += 1
                cycle += 1
                continue

            if intent.action is SoftwareIncUIAction.SET_TEAM_WORKING_HOURS:
                if _semantic_hours_match(observation.semantic_after, intent):
                    verify_working_hours(
                        initial.observation.semantic_after, observation.semantic_after, intent
                    )
                    return _result(
                        intent,
                        initial.observation,
                        observation,
                        gestures=gestures,
                        cycles=cycle,
                        dry_run=dry_run,
                        verified=True,
                        message=(
                            f"{intent.team_name} working hours are "
                            f"{_hour_text(intent.work_start)}-{_hour_text(intent.work_end)}; "
                            "the exact semantic postcondition is verified."
                        ),
                    )
                for field, target_id, expected in (
                    ("arrival_time", "arrival_time_input", _hour_text(intent.work_start)),
                    ("departure_time", "departure_time_input", _hour_text(intent.work_end)),
                ):
                    value = _office_text(observation.semantic_after, field, empty=True)
                    focused = _office_bool(observation.semantic_after, f"{field}_focused")
                    if value != expected:
                        if not focused:
                            current = await _send(
                                observer,
                                current,
                                _click(
                                    observation, _target(observation, target_id), f"focus {field}"
                                ),
                                intent=intent,
                                cycle=cycle,
                                operation_id=operation_id,
                                dry_run=dry_run,
                                trace_writer=trace_writer,
                            )
                            if dry_run:
                                return _dry_result(
                                    intent,
                                    initial.observation,
                                    current.observation,
                                    gestures,
                                    cycle,
                                    f"focus {field}",
                                )
                            gestures += 1
                            cycle += 1
                            selected_field = None
                            break
                        if selected_field != field:
                            current = await _send(
                                observer,
                                current,
                                _key(observation, target_id, f"select existing {field} text"),
                                intent=intent,
                                cycle=cycle,
                                operation_id=operation_id,
                                dry_run=dry_run,
                                trace_writer=trace_writer,
                            )
                            if dry_run:
                                return _dry_result(
                                    intent,
                                    initial.observation,
                                    current.observation,
                                    gestures,
                                    cycle,
                                    f"select existing {field} text",
                                )
                            gestures += 1
                            cycle += 1
                            selected_field = field
                            break
                        current = await _send(
                            observer,
                            current,
                            _text(observation, target_id, expected, f"enter exact {field}"),
                            intent=intent,
                            cycle=cycle,
                            operation_id=operation_id,
                            dry_run=dry_run,
                            trace_writer=trace_writer,
                        )
                        if dry_run:
                            return _dry_result(
                                intent,
                                initial.observation,
                                current.observation,
                                gestures,
                                cycle,
                                f"enter exact {field}",
                            )
                        if (
                            _office_text(current.observation.semantic_after, field, empty=True)
                            != expected
                        ):
                            raise SoftwareIncUIVerificationError(
                                f"exact visible {field} was not observed"
                            )
                        gestures += 1
                        cycle += 1
                        selected_field = None
                        break
                else:
                    current = await _send(
                        observer,
                        current,
                        _click(
                            observation,
                            _target(observation, "apply_working_hours"),
                            "apply exact team working hours",
                        ),
                        intent=intent,
                        cycle=cycle,
                        operation_id=operation_id,
                        dry_run=dry_run,
                        trace_writer=trace_writer,
                    )
                    if dry_run:
                        return _dry_result(
                            intent,
                            initial.observation,
                            current.observation,
                            gestures,
                            cycle,
                            "apply the exact schedule",
                        )
                    gestures += 1
                    verify_working_hours(
                        initial.observation.semantic_after,
                        current.observation.semantic_after,
                        intent,
                    )
                    return _result(
                        intent,
                        initial.observation,
                        current.observation,
                        gestures=gestures,
                        cycles=cycle,
                        dry_run=False,
                        verified=True,
                        message=(
                            f"{intent.team_name} working hours changed and verified semantically."
                        ),
                    )
                continue

            current = await _send(
                observer,
                current,
                _click(
                    observation,
                    _target(observation, "show_team_employees"),
                    "open employees for the selected team",
                ),
                intent=intent,
                cycle=cycle,
                operation_id=operation_id,
                dry_run=dry_run,
                trace_writer=trace_writer,
            )
            if dry_run:
                return _dry_result(
                    intent,
                    initial.observation,
                    current.observation,
                    gestures,
                    cycle,
                    "open the selected team's employees",
                )
            gestures += 1
            cycle += 1
            continue

        if scene is SoftwareIncUIScene.EMPLOYEE_MANAGEMENT:
            assert employee_id is not None
            selected = _office_text(observation.semantic_after, "selected_employees", empty=True)
            if selected != employee_id:
                current = await _send(
                    observer,
                    current,
                    _click(
                        observation,
                        _target(observation, f"employee_row_{employee_id}"),
                        "select the exact employee",
                    ),
                    intent=intent,
                    cycle=cycle,
                    operation_id=operation_id,
                    dry_run=dry_run,
                    trace_writer=trace_writer,
                )
                if dry_run:
                    return _dry_result(
                        intent,
                        initial.observation,
                        current.observation,
                        gestures,
                        cycle,
                        "select the exact employee",
                    )
                if (
                    _office_text(
                        current.observation.semantic_after, "selected_employees", empty=True
                    )
                    != employee_id
                ):
                    raise SoftwareIncUIVerificationError(
                        "the requested employee was not uniquely selected"
                    )
                gestures += 1
                cycle += 1
                continue
            current = await _send(
                observer,
                current,
                _click(
                    observation,
                    _target(observation, "open_role_selection"),
                    "open role selection for the exact employee",
                ),
                intent=intent,
                cycle=cycle,
                operation_id=operation_id,
                dry_run=dry_run,
                trace_writer=trace_writer,
            )
            if dry_run:
                return _dry_result(
                    intent,
                    initial.observation,
                    current.observation,
                    gestures,
                    cycle,
                    "open role selection",
                )
            gestures += 1
            cycle += 1
            continue

        if scene is SoftwareIncUIScene.ROLE_SELECTION:
            assert intent.role is not None
            index = _ROLE_INDEX[intent.role]
            states = _role_states(observation.semantic_after)
            if states.get(index) != "On":
                current = await _send(
                    observer,
                    current,
                    _click(
                        observation,
                        _target(observation, f"primary_role_{index}"),
                        f"enable {intent.role.value} role",
                    ),
                    intent=intent,
                    cycle=cycle,
                    operation_id=operation_id,
                    dry_run=dry_run,
                    trace_writer=trace_writer,
                )
                if dry_run:
                    return _dry_result(
                        intent,
                        initial.observation,
                        current.observation,
                        gestures,
                        cycle,
                        f"enable {intent.role.value}",
                    )
                if _role_states(current.observation.semantic_after).get(index) != "On":
                    raise SoftwareIncUIVerificationError(
                        "the requested visible role toggle did not become active"
                    )
                gestures += 1
                cycle += 1
                continue
            current = await _send(
                observer,
                current,
                _click(
                    observation,
                    _target(observation, "apply_roles"),
                    "apply the selected employee role",
                ),
                intent=intent,
                cycle=cycle,
                operation_id=operation_id,
                dry_run=dry_run,
                trace_writer=trace_writer,
            )
            if dry_run:
                return _dry_result(
                    intent,
                    initial.observation,
                    current.observation,
                    gestures,
                    cycle,
                    "apply the selected role",
                )
            gestures += 1
            verify_employee_role(
                initial.observation.semantic_after, current.observation.semantic_after, intent
            )
            return _result(
                intent,
                initial.observation,
                current.observation,
                gestures=gestures,
                cycles=cycle,
                dry_run=False,
                verified=True,
                message=(
                    f"{intent.employee_name} role assignment changed and verified semantically."
                ),
            )

        raise SoftwareIncUIObservationError(
            f"office workflow cannot continue from scene {scene.value}; no input was retried"
        )

    raise SoftwareIncUIVerificationError(
        f"office workflow exceeded {_MAXIMUM_CYCLES} bounded cycles"
    )


async def _send(
    observer: SoftwareIncUIObserver,
    current: ObservedSoftwareIncUI,
    gesture: InputGesture,
    *,
    intent: OfficeIntent,
    cycle: int,
    operation_id: UUID,
    dry_run: bool,
    trace_writer: TraceWriter,
) -> ObservedSoftwareIncUI:
    if not dry_run:
        observer.backend.execute(gesture, frame=current.observation.frame)
        after = await observer.observe()
        _continuity(current.observation, after.observation)
    else:
        after = current
    trace_writer(
        StaffingTraceRecord(
            operation_id=operation_id,
            action=intent.action,
            cycle=cycle,
            observation_frame_id=after.observation.frame.frame_id,
            bridge_sequence=after.observation.semantic_after.bridge_sequence,
            scene=after.observation.scene,
            projection_id=after.observation.projection_id,
            target_id=gesture.target_id,
            gesture=gesture,
            input_sent=not dry_run,
            verified=True,
            reason=(
                "fresh screenshot and semantic snapshot observed after one office gesture"
                if not dry_run
                else "dry run validated exactly one current-frame office gesture"
            ),
            recorded_at=datetime.now(UTC),
        )
    )
    return after


def _click(
    observation: SoftwareIncUIObservation, target: VisualTarget, effect: str
) -> InputGesture:
    if target.point is None:
        raise SoftwareIncUIValidationError("click target has no current-frame point")
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


def _key(observation: SoftwareIncUIObservation, target_id: str, effect: str) -> InputGesture:
    frame = observation.frame
    return InputGesture(
        kind=InputGestureKind.KEY,
        key_code=0,
        modifiers=(KeyModifier.COMMAND,),
        expected_process_id=frame.process_id,
        expected_window_id=frame.window_id,
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene=observation.scene.value,
        target_id=target_id,
        intended_effect=effect,
    )


def _text(
    observation: SoftwareIncUIObservation, target_id: str, value: str, effect: str
) -> InputGesture:
    frame = observation.frame
    return InputGesture(
        kind=InputGestureKind.TEXT,
        text=value,
        expected_process_id=frame.process_id,
        expected_window_id=frame.window_id,
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene=observation.scene.value,
        target_id=target_id,
        intended_effect=effect,
    )


def _target(observation: SoftwareIncUIObservation, target_id: str) -> VisualTarget:
    matches = [target for target in observation.targets if target.target_id == target_id]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(
            f"target {target_id!r} did not resolve exactly once in the fresh frame"
        )
    target = matches[0]
    if (
        target.confidence < 0.8
        or target.source_frame_id != observation.frame.frame_id
        or target.scene is not observation.scene
        or target.projection_id != observation.projection_id
        or target.expires_at <= datetime.now(UTC)
    ):
        raise SoftwareIncUIValidationError(f"target {target_id!r} is ambiguous or stale")
    return target


def _office_state(snapshot: GameSnapshot) -> dict[str, object]:
    surfaces = [surface for surface in snapshot.surfaces if surface.coverage.surface == "office_ui"]
    states = [
        entity
        for surface in surfaces
        for entity in surface.entities
        if entity.entity_type == "office_ui_state" and entity.entity_id == "current"
    ]
    if len(surfaces) != 1 or len(states) != 1:
        raise SoftwareIncUIObservationError("office UI state did not resolve exactly once")
    return dict(states[0].values)


def _office_text(snapshot: GameSnapshot, key: str, *, empty: bool = False) -> str:
    value = _office_state(snapshot).get(key)
    if not isinstance(value, str) or (not empty and not value):
        raise SoftwareIncUIObservationError(f"office UI field {key!r} is unavailable")
    return value


def _office_bool(snapshot: GameSnapshot, key: str) -> bool:
    value = _office_state(snapshot).get(key)
    if not isinstance(value, bool):
        raise SoftwareIncUIObservationError(f"office UI field {key!r} is unavailable")
    return value


def _role_states(snapshot: GameSnapshot) -> dict[int, str]:
    value = _office_text(snapshot, "primary_role_states", empty=True)
    states: dict[int, str] = {}
    for item in filter(None, value.split("|")):
        index, separator, state = item.partition(":")
        if separator and index.isdigit():
            states[int(index)] = state
    return states


def _semantic_hours_match(snapshot: GameSnapshot, intent: OfficeIntent) -> bool:
    try:
        readiness = project_team_readiness(snapshot, intent.team_name)
    except SoftwareIncUIValidationError:
        return False
    return readiness.work_start == intent.work_start and readiness.work_end == intent.work_end


def _employee_has_role(snapshot: GameSnapshot, employee_id: str, intent: OfficeIntent) -> bool:
    assert intent.role is not None
    surfaces = [surface for surface in snapshot.surfaces if surface.coverage.surface == "employees"]
    matches = [
        entity
        for surface in surfaces
        for entity in surface.entities
        if entity.entity_type == "employee" and entity.entity_id == employee_id
    ]
    return (
        len(matches) == 1
        and intent.role.value.casefold() in str(matches[0].values.get("role", "")).casefold()
    )


def _hour_text(value: Decimal | None) -> str:
    if value is None:
        raise SoftwareIncUIValidationError("exact whole-hour value is required")
    return str(int(value))


def _require_actionable(observation: SoftwareIncUIObservation) -> None:
    if observation.modal_state is not ModalState.NONE:
        raise SoftwareIncUIObservationError(
            f"cannot configure office while modal state is {observation.modal_state.value}"
        )
    if observation.scene in {
        SoftwareIncUIScene.UNKNOWN,
        SoftwareIncUIScene.BLOCKING_MODAL,
        SoftwareIncUIScene.HIRING_CONFIRMATION,
    }:
        raise SoftwareIncUIObservationError(
            f"cannot configure office from scene {observation.scene.value}"
        )
    if not observation.paused and observation.scene is not SoftwareIncUIScene.GAMEPLAY_RUNNING:
        raise SoftwareIncUIObservationError("office configuration requires the game paused")


def _continuity(before: SoftwareIncUIObservation, after: SoftwareIncUIObservation) -> None:
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
        raise SoftwareIncUIVerificationError("game, save, process, or window identity changed")


def _dry_result(
    intent: OfficeIntent,
    before: SoftwareIncUIObservation,
    after: SoftwareIncUIObservation,
    gestures: int,
    cycles: int,
    next_action: str,
) -> OfficeOperationResult:
    return _result(
        intent,
        before,
        after,
        gestures=gestures,
        cycles=cycles,
        dry_run=True,
        verified=True,
        message=f"Dry run: the next bounded cycle would {next_action}; no input was sent.",
    )


def _result(
    intent: OfficeIntent,
    before: SoftwareIncUIObservation,
    after: SoftwareIncUIObservation,
    *,
    gestures: int,
    cycles: int,
    dry_run: bool,
    verified: bool,
    message: str,
) -> OfficeOperationResult:
    return OfficeOperationResult(
        intent=intent,
        before=before,
        after=after,
        gestures_sent=gestures,
        cycles=cycles,
        dry_run=dry_run,
        verified=verified,
        message=message,
    )


__all__ = ["execute_office_intent"]
