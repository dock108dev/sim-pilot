"""One-gesture-per-cycle visible-UI workstation setup."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sim_pilot.computer_control.models import InputGesture, InputGestureKind, KeyModifier
from sim_pilot.game_bridge import GameSnapshot, ObservedEntity
from sim_pilot.software_inc.errors import (
    SoftwareIncUIObservationError,
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)

from .models import (
    ModalState,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    StaffingTraceRecord,
    VisualTarget,
)
from .observer import ObservedSoftwareIncUI, SoftwareIncUIObserver
from .trace import append_staffing_trace
from .workstation import (
    ApprovalProvider,
    WorkstationApproval,
    WorkstationIntent,
    WorkstationLineItem,
    WorkstationOperationResult,
    WorkstationPlan,
    build_workstation_plan,
    require_valid_workstation_approval,
    resolve_workstation_approval,
    verify_workstation_result,
)

ObserverFactory = Callable[[], SoftwareIncUIObserver]
TraceWriter = Callable[[StaffingTraceRecord], object]
Postcondition = Callable[[SoftwareIncUIObservation], bool]
_MAXIMUM_CYCLES = 96
_MAXIMUM_PREFLIGHT_CYCLES = 12
_MAXIMUM_ROOM_TARGET_ATTEMPTS = 4
_MAXIMUM_PLACEMENT_TARGET_ATTEMPTS = 8
_INPUT_REFRESH_THRESHOLD_SECONDS = 1.5
_MAXIMUM_INPUT_REFRESHES = 2
_ESCAPE = 53
_RETURN = 36
_A = 0


async def execute_workstation_intent(
    intent: WorkstationIntent,
    *,
    dry_run: bool = False,
    approval_provider: ApprovalProvider | None = None,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    trace_writer: TraceWriter = append_staffing_trace,
) -> WorkstationOperationResult:
    observer = observer_factory()
    observed = await observer.observe()
    plan = build_workstation_plan(intent, observed.observation)
    if dry_run:
        return _result(
            intent,
            plan,
            None,
            observed.observation,
            observed.observation,
            gestures=0,
            cycles=1,
            dry_run=True,
            verified=False,
            partial=True,
            message=_dry_run_message(plan),
        )
    if not plan.assign_room_to_team and not plan.line_items:
        verify_workstation_result(
            observed.observation.semantic_after,
            observed.observation.semantic_after,
            plan,
        )
        return _result(
            intent,
            plan,
            None,
            observed.observation,
            observed.observation,
            gestures=0,
            cycles=1,
            dry_run=False,
            verified=True,
            partial=False,
            message=(
                f"{plan.team_name} already has a verified valid workstation in room "
                f"{plan.room_id}; no approval, purchase, or input was required."
            ),
        )
    if approval_provider is None:
        raise SoftwareIncUIValidationError(
            "workstation setup requires approval for the exact catalog items and prices"
        )
    operation_id = uuid4()
    current, gestures, cycle = await _prepare_for_workstation_plan(
        observer,
        observed,
        intent,
        operation_id,
        trace_writer,
    )
    initial = current
    plan = build_workstation_plan(intent, initial.observation)
    approval = resolve_workstation_approval(plan, approved=approval_provider(plan))
    if not approval.approved:
        return _result(
            intent,
            plan,
            approval,
            initial.observation,
            initial.observation,
            gestures=gestures,
            cycles=cycle,
            dry_run=False,
            verified=False,
            partial=False,
            message=(
                "Exact workstation commitment was denied; reversible preflight gestures="
                f"{gestures}; no room assignment or furniture input was sent."
            ),
        )
    refreshed = await observer.observe()
    _continuity(initial.observation, refreshed.observation)
    _require_actionable(refreshed.observation)
    if refreshed.observation.scene is not SoftwareIncUIScene.GAMEPLAY_PAUSED:
        raise SoftwareIncUIValidationError(
            "game scene changed while workstation approval was pending; a fresh plan and "
            "approval are required"
        )
    current = refreshed
    require_valid_workstation_approval(plan, approval, current.observation)
    initial = current

    room_targets_tried: set[str] = set()
    placement_targets_tried: dict[int, set[str]] = {}
    placement_target_for_line: dict[int, str] = {}
    selected_search_for: int | None = None
    line_index = 0
    placed_anchors = {
        component.purpose: component.equipment_id for component in plan.reused_components
    }
    baseline_equipment = _room_equipment(initial.observation.semantic_after, plan.room_id)

    while cycle <= _MAXIMUM_CYCLES:
        current = await _refresh_stale_observation(observer, current)
        observation = current.observation
        _require_actionable(observation)
        snapshot = observation.semantic_after
        room = _room(snapshot, plan.room_id)
        assigned = _room_teams(room)
        assignment_complete = plan.team_name.casefold() in {name.casefold() for name in assigned}

        if not assignment_complete:
            if observation.scene is SoftwareIncUIScene.GAMEPLAY_RUNNING:
                current = await _send(
                    observer,
                    current,
                    _gesture(observation, InputGestureKind.CLICK, "pause_button", point=True),
                    intent,
                    operation_id,
                    cycle,
                    approval,
                    trace_writer,
                    postcondition=_gameplay_paused,
                )
            elif observation.scene in {
                SoftwareIncUIScene.MANAGE_TEAMS,
                SoftwareIncUIScene.CREATE_TEAM_FORM,
                SoftwareIncUIScene.HIRING_SETUP,
                SoftwareIncUIScene.APPLICANT_LIST,
                SoftwareIncUIScene.HIRING_CONFIRMATION,
                SoftwareIncUIScene.EMPLOYEE_MANAGEMENT,
                SoftwareIncUIScene.ROLE_SELECTION,
                SoftwareIncUIScene.SERVER_MANAGEMENT,
                SoftwareIncUIScene.BUILD_SEARCH,
                SoftwareIncUIScene.BUILD_MODE,
                SoftwareIncUIScene.FURNITURE_PLACEMENT,
            }:
                current = await _send(
                    observer,
                    current,
                    _gesture(observation, InputGestureKind.KEY, "escape_to_gameplay", key=_ESCAPE),
                    intent,
                    operation_id,
                    cycle,
                    approval,
                    trace_writer,
                )
            elif observation.scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
                if len(room_targets_tried) >= _MAXIMUM_ROOM_TARGET_ATTEMPTS:
                    raise SoftwareIncUIVerificationError(
                        "room context menu did not open after four distinct verified room "
                        "targets; stopped without assigning the room or buying furniture"
                    )
                target = _next_room_context_target(
                    observation, room_id=plan.room_id, tried=room_targets_tried
                )
                room_targets_tried.add(target.target_id)
                current = await _send(
                    observer,
                    current,
                    _gesture(
                        observation,
                        InputGestureKind.RIGHT_CLICK,
                        target.target_id,
                        target=target,
                    ),
                    intent,
                    operation_id,
                    cycle,
                    approval,
                    trace_writer,
                    postcondition=_room_context_opened,
                )
            elif observation.scene is SoftwareIncUIScene.ROOM_CONTEXT_MENU:
                target = _optional_target(observation, "change_room_team")
                if target is None:
                    current = await _send(
                        observer,
                        current,
                        _gesture(
                            observation, InputGestureKind.KEY, "close_wrong_context", key=_ESCAPE
                        ),
                        intent,
                        operation_id,
                        cycle,
                        approval,
                        trace_writer,
                    )
                else:
                    current = await _send(
                        observer,
                        current,
                        _gesture(
                            observation,
                            InputGestureKind.CLICK,
                            target.target_id,
                            target=target,
                        ),
                        intent,
                        operation_id,
                        cycle,
                        approval,
                        trace_writer,
                        postcondition=_room_team_selector_opened,
                    )
            elif observation.scene is SoftwareIncUIScene.ROOM_TEAM_SELECTION:
                selected = _build_text(snapshot, "room_team_selected", empty=True).split("|")
                selected = [value for value in selected if value]
                unauthorized = [
                    name
                    for name in selected
                    if name.casefold() != plan.team_name.casefold()
                    and name not in plan.previous_room_teams
                ]
                if unauthorized:
                    raise SoftwareIncUIValidationError(
                        "room team selector contains an unrelated team; refusing to evict or "
                        "alter it"
                    )
                if plan.team_name.casefold() not in {name.casefold() for name in selected}:
                    target = _target(observation, f"room_team_{plan.team_name}")
                    current = await _send(
                        observer,
                        current,
                        _gesture(
                            observation,
                            InputGestureKind.CLICK,
                            target.target_id,
                            target=target,
                        ),
                        intent,
                        operation_id,
                        cycle,
                        approval,
                        trace_writer,
                    )
                else:
                    target = _target(observation, "apply_room_teams")
                    current = await _send(
                        observer,
                        current,
                        _gesture(
                            observation,
                            InputGestureKind.CLICK,
                            target.target_id,
                            target=target,
                        ),
                        intent,
                        operation_id,
                        cycle,
                        approval,
                        trace_writer,
                    )
            else:
                raise SoftwareIncUIValidationError(
                    f"cannot safely assign the room from scene {observation.scene.value}"
                )
            gestures += 1
            cycle += 1
            continue

        if any(
            team not in plan.previous_room_teams and team != plan.team_name for team in assigned
        ):
            raise SoftwareIncUIVerificationError("room assignment added an unrelated team")

        if line_index >= len(plan.line_items):
            verify_workstation_result(
                initial.observation.semantic_after, observation.semantic_after, plan
            )
            return _result(
                intent,
                plan,
                approval,
                initial.observation,
                observation,
                gestures=gestures,
                cycles=cycle,
                dry_run=False,
                verified=True,
                partial=False,
                message=(
                    f"Prepared one verified workstation for {plan.team_name} in room "
                    f"{plan.room_id}; exact one-time cash change ${plan.total_one_time_cost:,.2f}, "
                    f"remaining cash ${_cash(snapshot):,.2f}."
                ),
            )

        line = plan.line_items[line_index]
        current_items = _room_equipment(snapshot, plan.room_id)
        added = {
            identity: entity
            for identity, entity in current_items.items()
            if identity not in baseline_equipment
            and _text(entity, "prefab_name").casefold() == line.catalog_item.prefab_name.casefold()
        }
        if added:
            if len(added) != 1:
                raise SoftwareIncUIVerificationError(
                    f"more than one {line.catalog_item.display_name} was added"
                )
            placed_anchors[line.purpose] = next(iter(added))
            expected_spend = sum(
                (item.expected_cash_charge for item in plan.line_items[: line_index + 1]),
                start=Decimal("0"),
            )
            if plan.observed_cash - _cash(snapshot) != expected_spend:
                raise SoftwareIncUIVerificationError(
                    f"cash change after {line.catalog_item.display_name} does not match the "
                    "exact approved catalog charge"
                )
            line_index += 1
            selected_search_for = None
            if observation.scene is SoftwareIncUIScene.FURNITURE_PLACEMENT:
                target = _target(observation, "open_build_mode")
                current = await _send(
                    observer,
                    current,
                    _gesture(
                        observation,
                        InputGestureKind.CLICK,
                        "stop_multiple_placement",
                        target=target,
                    ),
                    intent,
                    operation_id,
                    cycle,
                    approval,
                    trace_writer,
                    postcondition=_furniture_placement_closed,
                )
                gestures += 1
            cycle += 1
            continue

        if observation.scene is SoftwareIncUIScene.GAMEPLAY_RUNNING:
            current = await _send(
                observer,
                current,
                _gesture(observation, InputGestureKind.CLICK, "pause_button", point=True),
                intent,
                operation_id,
                cycle,
                approval,
                trace_writer,
            )
        elif observation.scene in {
            SoftwareIncUIScene.MANAGE_TEAMS,
            SoftwareIncUIScene.CREATE_TEAM_FORM,
            SoftwareIncUIScene.HIRING_SETUP,
            SoftwareIncUIScene.APPLICANT_LIST,
            SoftwareIncUIScene.HIRING_CONFIRMATION,
            SoftwareIncUIScene.EMPLOYEE_MANAGEMENT,
            SoftwareIncUIScene.ROLE_SELECTION,
            SoftwareIncUIScene.SERVER_MANAGEMENT,
            SoftwareIncUIScene.ROOM_CONTEXT_MENU,
            SoftwareIncUIScene.ROOM_TEAM_SELECTION,
        }:
            current = await _send(
                observer,
                current,
                _gesture(observation, InputGestureKind.KEY, "escape_to_gameplay", key=_ESCAPE),
                intent,
                operation_id,
                cycle,
                approval,
                trace_writer,
            )
        elif observation.scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
            target = _target(observation, "open_build_mode")
            current = await _send(
                observer,
                current,
                _gesture(
                    observation,
                    InputGestureKind.CLICK,
                    target.target_id,
                    target=target,
                ),
                intent,
                operation_id,
                cycle,
                approval,
                trace_writer,
                postcondition=_build_mode_opened,
            )
        elif observation.scene is SoftwareIncUIScene.BUILD_MODE:
            target_id = f"build_catalog_item:{line.catalog_item.prefab_name}"
            target = _optional_target(observation, target_id)
            if target is None:
                raise SoftwareIncUIValidationError(
                    f"approved catalog item {line.catalog_item.display_name!r} is not an "
                    "exact visible build-palette target; no search or scrolling was guessed"
                )
            current = await _send(
                observer,
                current,
                _gesture(
                    observation,
                    InputGestureKind.CLICK,
                    target.target_id,
                    target=target,
                ),
                intent,
                operation_id,
                cycle,
                approval,
                trace_writer,
                postcondition=lambda after, approved=line: _approved_furniture_selected(
                    after, approved
                ),
            )
        elif observation.scene is SoftwareIncUIScene.BUILD_SEARCH:
            title = line.catalog_item.search_title
            current_text = _build_text(snapshot, "search_text", empty=True)
            focused = _build_bool(snapshot, "search_focused")
            if current_text != title:
                if not focused:
                    target = _target(observation, "build_search_input")
                    gesture = _gesture(
                        observation,
                        InputGestureKind.CLICK,
                        target.target_id,
                        target=target,
                    )
                elif selected_search_for != line_index:
                    gesture = _gesture(
                        observation,
                        InputGestureKind.KEY,
                        "select_build_search_text",
                        key=_A,
                        modifiers=(KeyModifier.COMMAND,),
                    )
                    selected_search_for = line_index
                else:
                    gesture = _gesture(
                        observation,
                        InputGestureKind.TEXT,
                        "enter_exact_catalog_title",
                        text=title,
                    )
                    selected_search_for = None
                current = await _send(
                    observer,
                    current,
                    gesture,
                    intent,
                    operation_id,
                    cycle,
                    approval,
                    trace_writer,
                )
            else:
                results = tuple(
                    filter(None, _build_text(snapshot, "search_results", empty=True).split("|"))
                )
                if not results or results[0].casefold() != title.casefold():
                    raise SoftwareIncUIValidationError(
                        f"global search did not resolve {title!r} as the unique first result"
                    )
                target = _target(observation, "build_search_result_0")
                current = await _send(
                    observer,
                    current,
                    _gesture(
                        observation,
                        InputGestureKind.CLICK,
                        target.target_id,
                        target=target,
                    ),
                    intent,
                    operation_id,
                    cycle,
                    approval,
                    trace_writer,
                )
        elif observation.scene is SoftwareIncUIScene.FURNITURE_PLACEMENT:
            if (
                _build_text(snapshot, "builder_prefab_name").casefold()
                != line.catalog_item.prefab_name.casefold()
                or _build_decimal(snapshot, "builder_cost") != line.catalog_item.one_time_cost
            ):
                raise SoftwareIncUIValidationError(
                    "active furniture preview does not match the approved catalog identity "
                    "and price"
                )
            tried = placement_targets_tried.setdefault(line_index, set())
            ready_target_id = placement_target_for_line.get(line_index)
            if ready_target_id is None or not _build_bool(snapshot, "preview_valid"):
                if len(tried) >= _MAXIMUM_PLACEMENT_TARGET_ATTEMPTS:
                    raise SoftwareIncUIVerificationError(
                        "approved furniture did not reach a valid placement preview after "
                        "eight distinct verified room targets; no placement click was sent"
                    )
                target = _placement_target(
                    observation,
                    plan,
                    line.purpose,
                    placed_anchors,
                    tried,
                )
                tried.add(target.target_id)
                placement_target_for_line[line_index] = target.target_id
                current = await _send(
                    observer,
                    current,
                    _gesture(
                        observation,
                        InputGestureKind.MOVE,
                        target.target_id,
                        target=target,
                    ),
                    intent,
                    operation_id,
                    cycle,
                    approval,
                    trace_writer,
                    postcondition=lambda after, approved=line: _approved_preview_valid(
                        after, approved, plan.room_id
                    ),
                )
            else:
                if _build_text(snapshot, "builder_room_id") != plan.room_id:
                    raise SoftwareIncUIValidationError(
                        "valid furniture preview belongs to a different room"
                    )
                # Always click the exact fresh room/anchor target that the cursor was moved
                # to in the prior cycle. The builder's initial preview is created under the
                # build-palette cursor and is not a safe placement target even when the game
                # reports its cached LastRoom as valid.
                target = _target(observation, ready_target_id)
                expected_ids = frozenset(current_items)
                current = await _send(
                    observer,
                    current,
                    _gesture(
                        observation,
                        InputGestureKind.CLICK,
                        target.target_id,
                        target=target,
                    ),
                    intent,
                    operation_id,
                    cycle,
                    approval,
                    trace_writer,
                    postcondition=lambda after, approved=line, prior=expected_ids: (
                        _approved_item_added(after, approved, plan.room_id, prior)
                    ),
                )
                if not _approved_item_added(current.observation, line, plan.room_id, expected_ids):
                    raise SoftwareIncUIVerificationError(
                        f"placement click did not add the approved "
                        f"{line.catalog_item.display_name}; it will not be retried"
                    )
        else:
            raise SoftwareIncUIValidationError(
                f"cannot continue workstation setup from scene {observation.scene.value}"
            )
        gestures += 1
        cycle += 1

    raise SoftwareIncUIVerificationError(
        f"workstation setup exceeded {_MAXIMUM_CYCLES} verified one-gesture cycles"
    )


async def _prepare_for_workstation_plan(
    observer: SoftwareIncUIObserver,
    current: ObservedSoftwareIncUI,
    intent: WorkstationIntent,
    operation_id: UUID,
    trace_writer: TraceWriter,
) -> tuple[ObservedSoftwareIncUI, int, int]:
    """Reach paused gameplay before approval using only reversible, traced navigation."""
    gestures = 0
    for cycle in range(1, _MAXIMUM_PREFLIGHT_CYCLES + 1):
        current = await _refresh_stale_observation(observer, current)
        observation = current.observation
        _require_actionable(observation)
        if observation.scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
            return current, gestures, cycle
        postcondition: Postcondition | None = None
        if observation.scene is SoftwareIncUIScene.PAUSE_MENU:
            gesture = _gesture(
                observation,
                InputGestureKind.CLICK,
                "close_pause_menu",
                point=True,
            )
            postcondition = _pause_menu_closed
        elif observation.scene is SoftwareIncUIScene.GAMEPLAY_RUNNING:
            gesture = _gesture(
                observation,
                InputGestureKind.CLICK,
                "pause_button",
                point=True,
            )
            postcondition = _gameplay_paused
        elif observation.scene is SoftwareIncUIScene.CONTRACT_BROWSER:
            gesture = _gesture(
                observation,
                InputGestureKind.CLICK,
                "close_contract_browser",
                point=True,
            )
            postcondition = _contract_browser_closed
        elif observation.scene is SoftwareIncUIScene.ROOM_TEAM_SELECTION:
            gesture = _gesture(
                observation,
                InputGestureKind.CLICK,
                "close_room_team_selection",
                point=True,
            )
            postcondition = _room_team_selector_closed
        elif observation.scene is SoftwareIncUIScene.BUILD_MODE:
            gesture = _gesture(
                observation,
                InputGestureKind.CLICK,
                "open_build_mode",
                point=True,
            )
            postcondition = _build_mode_closed
        elif observation.scene is SoftwareIncUIScene.FURNITURE_PLACEMENT:
            gesture = _gesture(
                observation,
                InputGestureKind.CLICK,
                "open_build_mode",
                point=True,
            )
            postcondition = _furniture_placement_closed
        elif observation.scene in _REVERSIBLE_PREFLIGHT_SCENES:
            gesture = _gesture(
                observation,
                InputGestureKind.KEY,
                "escape_to_paused_gameplay",
                key=_ESCAPE,
            )
        else:
            raise SoftwareIncUIValidationError(
                "cannot safely prepare a workstation plan from scene "
                f"{observation.scene.value}; no approval was requested"
            )
        current = await _send_preapproval(
            observer,
            current,
            gesture,
            intent,
            operation_id,
            cycle,
            trace_writer,
            postcondition=postcondition,
        )
        gestures += 1  # noqa: SIM113 - count only successfully verified preflight input
    raise SoftwareIncUIVerificationError(
        "workstation preflight did not reach paused gameplay within its bounded cycles"
    )


_REVERSIBLE_PREFLIGHT_SCENES = frozenset(
    {
        SoftwareIncUIScene.MANAGEMENT_NAVIGATION,
        SoftwareIncUIScene.MANAGE_TEAMS,
        SoftwareIncUIScene.CREATE_TEAM_FORM,
        SoftwareIncUIScene.HIRING_SETUP,
        SoftwareIncUIScene.APPLICANT_LIST,
        SoftwareIncUIScene.HIRING_CONFIRMATION,
        SoftwareIncUIScene.HIRING_COMPLETE,
        SoftwareIncUIScene.EMPLOYEE_MANAGEMENT,
        SoftwareIncUIScene.ROLE_SELECTION,
        SoftwareIncUIScene.SERVER_MANAGEMENT,
        SoftwareIncUIScene.BUILD_SEARCH,
        SoftwareIncUIScene.BUILD_MODE,
        SoftwareIncUIScene.FURNITURE_PLACEMENT,
        SoftwareIncUIScene.ROOM_CONTEXT_MENU,
        SoftwareIncUIScene.ROOM_TEAM_SELECTION,
        SoftwareIncUIScene.CONTRACT_BROWSER,
        SoftwareIncUIScene.CONTRACT_TEAM_SELECTION,
        SoftwareIncUIScene.CONTRACT_REVIEW_SETUP,
    }
)


async def _send_preapproval(
    observer: SoftwareIncUIObserver,
    current: ObservedSoftwareIncUI,
    gesture: InputGesture,
    intent: WorkstationIntent,
    operation_id: UUID,
    cycle: int,
    trace_writer: TraceWriter,
    postcondition: Postcondition | None = None,
) -> ObservedSoftwareIncUI:
    observer.backend.execute(gesture, frame=current.observation.frame)
    _write_workstation_trace(
        trace_writer,
        current.observation,
        intent=intent,
        operation_id=operation_id,
        cycle=cycle,
        gesture=gesture,
        approval=None,
        verified=False,
        reason=(
            "preapproval input was sent; postcondition is pending and the gesture must not "
            "be retried until a fresh observation resolves its effect"
        ),
    )
    after = await observer.observe()
    _continuity(current.observation, after.observation)
    verified = postcondition(after.observation) if postcondition is not None else True
    _write_workstation_trace(
        trace_writer,
        after.observation,
        intent=intent,
        operation_id=operation_id,
        cycle=cycle,
        gesture=gesture,
        approval=None,
        verified=verified,
        reason=(
            "reversible preflight gesture reached its verified fresh scene before workstation "
            "planning and approval"
            if verified
            else "fresh observation proved the reversible preflight scene transition did not "
            "occur; the same gesture will not be retried"
        ),
    )
    return after


async def _send(
    observer: SoftwareIncUIObserver,
    current: ObservedSoftwareIncUI,
    gesture: InputGesture,
    intent: WorkstationIntent,
    operation_id: UUID,
    cycle: int,
    approval: WorkstationApproval,
    trace_writer: TraceWriter,
    postcondition: Postcondition | None = None,
) -> ObservedSoftwareIncUI:
    observer.backend.execute(gesture, frame=current.observation.frame)
    _write_workstation_trace(
        trace_writer,
        current.observation,
        intent=intent,
        operation_id=operation_id,
        cycle=cycle,
        gesture=gesture,
        approval=approval,
        verified=False,
        reason=(
            "approved input was sent; postcondition is pending and the gesture must not be "
            "retried until a fresh observation resolves its effect"
        ),
    )
    after = await observer.observe()
    _continuity(current.observation, after.observation)
    verified = postcondition(after.observation) if postcondition is not None else True
    _write_workstation_trace(
        trace_writer,
        after.observation,
        intent=intent,
        operation_id=operation_id,
        cycle=cycle,
        gesture=gesture,
        approval=approval,
        verified=verified,
        reason=(
            "fresh screenshot and semantic snapshot verified the workstation gesture postcondition"
            if verified
            else "fresh screenshot and semantic snapshot proved the intended scene transition "
            "did not occur; the same gesture will not be retried"
        ),
    )
    return after


def _write_workstation_trace(
    trace_writer: TraceWriter,
    observation: SoftwareIncUIObservation,
    *,
    intent: WorkstationIntent,
    operation_id: UUID,
    cycle: int,
    gesture: InputGesture,
    approval: WorkstationApproval | None,
    verified: bool,
    reason: str,
) -> None:
    trace_writer(
        StaffingTraceRecord(
            operation_id=operation_id,
            action=intent.action,
            cycle=cycle,
            plan_fingerprint=None if approval is None else approval.plan_fingerprint,
            approval_id=None if approval is None else approval.approval_id,
            observation_frame_id=observation.frame.frame_id,
            bridge_sequence=observation.semantic_after.bridge_sequence,
            scene=observation.scene,
            projection_id=observation.projection_id,
            target_id=gesture.target_id,
            gesture=gesture,
            input_sent=True,
            verified=verified,
            reason=reason,
            recorded_at=datetime.now(UTC),
        )
    )


def _gesture(
    observation: SoftwareIncUIObservation,
    kind: InputGestureKind,
    target_id: str,
    *,
    target: VisualTarget | None = None,
    point: bool = False,
    key: int | None = None,
    modifiers: tuple[KeyModifier, ...] = (),
    text: str | None = None,
) -> InputGesture:
    if point:
        target = _target(observation, target_id)
    frame = observation.frame
    return InputGesture(
        kind=kind,
        point=None if target is None else target.point,
        key_code=key,
        modifiers=modifiers,
        text=text,
        expected_process_id=frame.process_id,
        expected_window_id=frame.window_id,
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene=observation.scene.value,
        target_id=target_id,
        intended_effect=target_id.replace("_", " "),
    )


def _placement_target(
    observation: SoftwareIncUIObservation,
    plan: WorkstationPlan,
    purpose: str,
    anchors: dict[str, str],
    tried: set[str],
) -> VisualTarget:
    if purpose in {"computer", "chair"} and "work_surface" in anchors:
        anchor_id = f"equipment_target_{anchors['work_surface']}"
        anchor = _optional_target(observation, anchor_id)
        if anchor is not None and anchor_id not in tried:
            return anchor
    return _next_target(
        observation,
        prefix=f"room_candidate_{plan.room_id}_",
        tried=tried,
    )


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
        raise SoftwareIncUIValidationError(f"target {target_id!r} is ambiguous or stale")
    return target


def _optional_target(observation: SoftwareIncUIObservation, target_id: str) -> VisualTarget | None:
    matches = [target for target in observation.targets if target.target_id == target_id]
    return _target(observation, target_id) if len(matches) == 1 else None


def _next_target(
    observation: SoftwareIncUIObservation,
    *,
    prefix: str,
    tried: set[str],
) -> VisualTarget:
    candidates = sorted(
        (target for target in observation.targets if target.target_id.startswith(prefix)),
        key=lambda target: target.target_id,
    )
    for candidate in candidates:
        if candidate.target_id not in tried:
            return _target(observation, candidate.target_id)
    raise SoftwareIncUIValidationError(
        f"no untried, visible target remains for {prefix.rstrip('_')}"
    )


def _next_room_context_target(
    observation: SoftwareIncUIObservation,
    *,
    room_id: str,
    tried: set[str],
) -> VisualTarget:
    prefix = f"room_candidate_{room_id}_"
    center_id = f"{prefix}0"
    center = _optional_target(observation, center_id)
    if center is not None and center_id not in tried:
        return center
    candidates = sorted(
        (
            target
            for target in observation.targets
            if target.target_id.startswith(prefix) and target.target_id not in tried
        ),
        key=lambda target: (-target.confidence, target.target_id),
    )
    if candidates:
        return _target(observation, candidates[0].target_id)
    raise SoftwareIncUIValidationError(
        f"no untried, visible target remains for {prefix.rstrip('_')}"
    )


def _require_actionable(observation: SoftwareIncUIObservation) -> None:
    if (
        observation.modal_state is not ModalState.NONE
        and observation.scene is not SoftwareIncUIScene.PAUSE_MENU
    ):
        raise SoftwareIncUIValidationError(
            f"workstation setup is blocked by modal state {observation.modal_state.value}"
        )
    if observation.scene in {SoftwareIncUIScene.UNKNOWN, SoftwareIncUIScene.BLOCKING_MODAL}:
        raise SoftwareIncUIValidationError(
            f"workstation setup does not support scene {observation.scene.value}"
        )


def _continuity(before: SoftwareIncUIObservation, after: SoftwareIncUIObservation) -> None:
    left = before.semantic_after
    right = after.semantic_after
    if (
        left.game_session_id != right.game_session_id
        or left.save_identity != right.save_identity
        or left.bridge_instance_id != right.bridge_instance_id
        or right.bridge_sequence <= left.bridge_sequence
    ):
        raise SoftwareIncUIVerificationError("bridge, save, or game-session identity changed")


async def _refresh_stale_observation(
    observer: SoftwareIncUIObserver,
    current: ObservedSoftwareIncUI,
) -> ObservedSoftwareIncUI:
    """Refresh an old screenshot before target resolution, without sending input."""
    for _attempt in range(_MAXIMUM_INPUT_REFRESHES):
        if (
            current.observation.frame.age_seconds(datetime.now(UTC))
            <= _INPUT_REFRESH_THRESHOLD_SECONDS
        ):
            return current
        refreshed = await observer.observe()
        _continuity(current.observation, refreshed.observation)
        current = refreshed
    if current.observation.frame.age_seconds(datetime.now(UTC)) > _INPUT_REFRESH_THRESHOLD_SECONDS:
        raise SoftwareIncUIValidationError(
            "synchronized screenshots remained too old for safe input after two read-only "
            "refreshes; no gesture was sent"
        )
    return current


def _pause_menu_closed(observation: SoftwareIncUIObservation) -> bool:
    return observation.scene is not SoftwareIncUIScene.PAUSE_MENU


def _gameplay_paused(observation: SoftwareIncUIObservation) -> bool:
    return observation.scene is SoftwareIncUIScene.GAMEPLAY_PAUSED


def _contract_browser_closed(observation: SoftwareIncUIObservation) -> bool:
    return observation.scene is not SoftwareIncUIScene.CONTRACT_BROWSER


def _room_team_selector_opened(observation: SoftwareIncUIObservation) -> bool:
    return observation.scene is SoftwareIncUIScene.ROOM_TEAM_SELECTION


def _room_context_opened(observation: SoftwareIncUIObservation) -> bool:
    return observation.scene is SoftwareIncUIScene.ROOM_CONTEXT_MENU


def _room_team_selector_closed(observation: SoftwareIncUIObservation) -> bool:
    return observation.scene is not SoftwareIncUIScene.ROOM_TEAM_SELECTION


def _build_mode_opened(observation: SoftwareIncUIObservation) -> bool:
    return observation.scene is SoftwareIncUIScene.BUILD_MODE


def _furniture_placement_closed(observation: SoftwareIncUIObservation) -> bool:
    return observation.scene is not SoftwareIncUIScene.FURNITURE_PLACEMENT


def _approved_furniture_selected(
    observation: SoftwareIncUIObservation,
    line: WorkstationLineItem,
) -> bool:
    snapshot = observation.semantic_after
    return (
        observation.scene is SoftwareIncUIScene.FURNITURE_PLACEMENT
        and _build_text(snapshot, "builder_prefab_name").casefold()
        == line.catalog_item.prefab_name.casefold()
        and _build_decimal(snapshot, "builder_cost") == line.catalog_item.one_time_cost
    )


def _approved_preview_valid(
    observation: SoftwareIncUIObservation,
    line: WorkstationLineItem,
    room_id: str,
) -> bool:
    snapshot = observation.semantic_after
    return (
        _approved_furniture_selected(observation, line)
        and _build_bool(snapshot, "preview_valid")
        and _build_text(snapshot, "builder_room_id") == room_id
    )


def _approved_item_added(
    observation: SoftwareIncUIObservation,
    line: WorkstationLineItem,
    room_id: str,
    previous_ids: frozenset[str],
) -> bool:
    added = {
        identity: entity
        for identity, entity in _room_equipment(observation.semantic_after, room_id).items()
        if identity not in previous_ids
        and _text(entity, "prefab_name").casefold() == line.catalog_item.prefab_name.casefold()
    }
    return len(added) == 1


def _build_mode_closed(observation: SoftwareIncUIObservation) -> bool:
    return observation.scene is not SoftwareIncUIScene.BUILD_MODE


def _surface(snapshot: GameSnapshot, name: str):
    matches = [surface for surface in snapshot.surfaces if surface.coverage.surface == name]
    if len(matches) != 1:
        raise SoftwareIncUIObservationError(f"{name} surface did not resolve exactly once")
    return matches[0]


def _build_state(snapshot: GameSnapshot) -> dict[str, object]:
    states = [
        entity
        for entity in _surface(snapshot, "build_ui").entities
        if entity.entity_type == "build_ui_state" and entity.entity_id == "current"
    ]
    if len(states) != 1:
        raise SoftwareIncUIObservationError("build UI state did not resolve exactly once")
    return dict(states[0].values)


def _build_text(snapshot: GameSnapshot, key: str, *, empty: bool = False) -> str:
    value = _build_state(snapshot).get(key)
    if not isinstance(value, str) or (not empty and not value):
        raise SoftwareIncUIObservationError(f"build UI field {key!r} is unavailable")
    return value


def _build_bool(snapshot: GameSnapshot, key: str) -> bool:
    value = _build_state(snapshot).get(key)
    if not isinstance(value, bool):
        raise SoftwareIncUIObservationError(f"build UI field {key!r} is unavailable")
    return value


def _build_decimal(snapshot: GameSnapshot, key: str) -> Decimal:
    value = _build_state(snapshot).get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise SoftwareIncUIObservationError(f"build UI field {key!r} is unavailable")
    return Decimal(str(value))


def _room(snapshot: GameSnapshot, room_id: str) -> ObservedEntity:
    matches = [
        entity
        for entity in _surface(snapshot, "offices").entities
        if entity.entity_type == "office_room" and entity.entity_id == room_id
    ]
    if len(matches) != 1:
        raise SoftwareIncUIObservationError(f"office room {room_id!r} did not resolve once")
    return matches[0]


def _room_equipment(snapshot: GameSnapshot, room_id: str) -> dict[str, ObservedEntity]:
    return {
        entity.entity_id: entity
        for entity in _surface(snapshot, "offices").entities
        if entity.entity_type == "office_equipment" and entity.values.get("room_id") == room_id
    }


def _room_teams(room: ObservedEntity) -> tuple[str, ...]:
    return tuple(filter(None, _text(room, "assigned_teams", empty=True).split("|")))


def _cash(snapshot: GameSnapshot) -> Decimal:
    entities = [
        entity
        for entity in _surface(snapshot, "finances").entities
        if entity.entity_type == "company_finances"
    ]
    if len(entities) != 1:
        raise SoftwareIncUIObservationError("company finances did not resolve once")
    value = entities[0].values.get("cash")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise SoftwareIncUIObservationError("company cash is unavailable")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _text(entity: ObservedEntity, key: str, *, empty: bool = False) -> str:
    value = entity.values.get(key)
    if not isinstance(value, str) or (not empty and not value):
        raise SoftwareIncUIObservationError(f"{entity.entity_id}.{key} is unavailable")
    return value


def _dry_run_message(plan: WorkstationPlan) -> str:
    lines = (
        ", ".join(
            f"1x {line.catalog_item.display_name} at ${line.total_price:,.2f}"
            + (" from inventory" if line.expected_cash_charge == 0 else "")
            for line in plan.line_items
        )
        or "no furniture purchase"
    )
    reused = ", ".join(f"existing {component.display_name}" for component in plan.reused_components)
    reuse_detail = f"; reuse {reused}" if reused else ""
    room_action = (
        f"assign room {plan.room_id} to {plan.team_name}"
        if plan.assign_room_to_team
        else f"room {plan.room_id} is already assigned to {plan.team_name}"
    )
    return (
        f"Dry run: {room_action}{reuse_detail}; {lines}; "
        "exact cash charge "
        f"${plan.total_one_time_cost:,.2f}; projected cash ${plan.projected_cash_after:,.2f}; "
        "no input was sent."
    )


def _result(
    intent: WorkstationIntent,
    plan: WorkstationPlan,
    approval: WorkstationApproval | None,
    before: SoftwareIncUIObservation,
    after: SoftwareIncUIObservation,
    *,
    gestures: int,
    cycles: int,
    dry_run: bool,
    verified: bool,
    partial: bool,
    message: str,
) -> WorkstationOperationResult:
    return WorkstationOperationResult(
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
        message=message,
        completed_at=datetime.now(UTC),
    )


__all__ = ["execute_workstation_intent"]
