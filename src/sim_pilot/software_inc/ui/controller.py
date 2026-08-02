"""Bounded, verified Software Inc. visible-UI actions."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from sim_pilot.computer_control.models import InputGesture, InputGestureKind
from sim_pilot.game_bridge.models import GameSnapshot
from sim_pilot.software_inc.errors import (
    SoftwareIncUIObservationError,
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)

from .models import (
    ModalState,
    SoftwareIncUIAction,
    SoftwareIncUIDoResult,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    SoftwareIncUITraceRecord,
    VisualTarget,
)
from .observer import ObservedSoftwareIncUI, SoftwareIncUIObserver
from .trace import append_ui_trace

_TEAM_MANAGEMENT_SCENES = frozenset(
    {SoftwareIncUIScene.MANAGE_TEAMS, SoftwareIncUIScene.CREATE_TEAM_FORM}
)


def parse_ui_action(instruction: str) -> SoftwareIncUIAction:
    normalized = " ".join(instruction.strip().casefold().replace("-", " ").split())
    if normalized in {"pause", "pause it", "pause the game", "stop time"}:
        return SoftwareIncUIAction.PAUSE
    if normalized in {"resume", "resume it", "resume the game", "start time", "unpause"}:
        return SoftwareIncUIAction.RESUME
    if normalized in {
        "open manage teams",
        "open manage teams window",
        "open team management",
        "show manage teams",
        "show me manage teams",
    }:
        return SoftwareIncUIAction.OPEN_MANAGE_TEAMS
    raise SoftwareIncUIValidationError(
        "unsupported Software Inc. UI request; choose pause, resume, or open manage teams"
    )


async def execute_ui_action(
    action: SoftwareIncUIAction,
    *,
    dry_run: bool = False,
    observer_factory: Callable[[], SoftwareIncUIObserver] = SoftwareIncUIObserver,
    trace_writer: Callable[[SoftwareIncUITraceRecord], object] = append_ui_trace,
) -> SoftwareIncUIDoResult:
    observer = observer_factory()
    before = await observer.observe()
    if (
        action is SoftwareIncUIAction.OPEN_MANAGE_TEAMS
        and before.observation.scene in _TEAM_MANAGEMENT_SCENES
    ):
        return await _execute_open_manage_teams(
            before,
            observer=observer,
            dry_run=dry_run,
            trace_writer=trace_writer,
        )
    _require_actionable(before)
    if action in {SoftwareIncUIAction.PAUSE, SoftwareIncUIAction.RESUME}:
        return await _execute_time_control(
            action,
            before,
            observer=observer,
            dry_run=dry_run,
            trace_writer=trace_writer,
        )
    return await _execute_open_manage_teams(
        before,
        observer=observer,
        dry_run=dry_run,
        trace_writer=trace_writer,
    )


async def _execute_time_control(
    action: SoftwareIncUIAction,
    before: ObservedSoftwareIncUI,
    *,
    observer: SoftwareIncUIObserver,
    dry_run: bool,
    trace_writer: Callable[[SoftwareIncUITraceRecord], object],
    cycle: int = 1,
) -> SoftwareIncUIDoResult:
    wants_paused = action is SoftwareIncUIAction.PAUSE
    if before.observation.paused is wants_paused:
        _trace(
            trace_writer,
            action,
            cycle,
            before.observation,
            target_id="pause_button" if wants_paused else "resume_button",
            gesture=None,
            input_sent=False,
            verified=True,
            reason="requested simulation state was already observed",
        )
        return _result(
            action,
            before.observation,
            before.observation,
            gestures=0,
            cycles=cycle,
            dry_run=dry_run,
            message=f"Software Inc. is already {'paused' if wants_paused else 'running'}.",
        )
    target = _target(before, "pause_button" if wants_paused else "resume_button")
    gesture = _click_gesture(
        before.observation,
        target,
        effect="pause simulation" if wants_paused else "resume simulation",
    )
    if dry_run:
        _trace(
            trace_writer,
            action,
            cycle,
            before.observation,
            target_id=target.target_id,
            gesture=gesture,
            input_sent=False,
            verified=True,
            reason="dry run validated one bounded key gesture",
        )
        return _result(
            action,
            before.observation,
            before.observation,
            gestures=0,
            cycles=cycle,
            dry_run=True,
            message=(
                f"Dry run: would {'pause' if wants_paused else 'resume'} "
                "with one visible time-control click."
            ),
        )
    observer.backend.execute(gesture, frame=before.observation.frame)
    try:
        after = await observer.observe()
    except Exception as error:
        _trace(
            trace_writer,
            action,
            cycle,
            before.observation,
            target_id=target.target_id,
            gesture=gesture,
            input_sent=True,
            verified=False,
            reason="fresh post-input observation failed; no retry attempted",
        )
        raise SoftwareIncUIVerificationError(
            "time-control input was sent but fresh verification failed; no retry attempted"
        ) from error
    expected_scene = (
        SoftwareIncUIScene.GAMEPLAY_PAUSED if wants_paused else SoftwareIncUIScene.GAMEPLAY_RUNNING
    )
    if (
        after.observation.paused is not wants_paused
        or after.observation.scene is not expected_scene
    ):
        _trace(
            trace_writer,
            action,
            cycle,
            after.observation,
            target_id=target.target_id,
            gesture=gesture,
            input_sent=True,
            verified=False,
            reason="semantic and visual time-control postcondition was not observed",
        )
        raise SoftwareIncUIVerificationError(
            "time-control gesture effect was not independently verified; no retry attempted"
        )
    _require_identity_continuity(before.observation, after.observation)
    _trace(
        trace_writer,
        action,
        cycle,
        after.observation,
        target_id=target.target_id,
        gesture=gesture,
        input_sent=True,
        verified=True,
        reason="semantic and visual time-control postcondition verified",
    )
    return _result(
        action,
        before.observation,
        after.observation,
        gestures=1,
        cycles=cycle,
        dry_run=False,
        message=f"Software Inc. {'paused' if wants_paused else 'resumed'}; effect verified.",
        expected=("game_state.force_pause", "game_state.simulation_speed"),
    )


async def _execute_open_manage_teams(
    before: ObservedSoftwareIncUI,
    *,
    observer: SoftwareIncUIObserver,
    dry_run: bool,
    trace_writer: Callable[[SoftwareIncUITraceRecord], object],
) -> SoftwareIncUIDoResult:
    if before.observation.scene in _TEAM_MANAGEMENT_SCENES:
        _trace(
            trace_writer,
            SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
            1,
            before.observation,
            target_id=None,
            gesture=None,
            input_sent=False,
            verified=True,
            reason="Manage Teams was already visibly open",
        )
        return _result(
            SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
            before.observation,
            before.observation,
            gestures=0,
            cycles=1,
            dry_run=dry_run,
            message="Manage Teams is already visibly open.",
        )
    current = before
    gestures = 0
    cycle = 1
    if not current.observation.paused:
        pause_result = await _execute_time_control(
            SoftwareIncUIAction.PAUSE,
            current,
            observer=observer,
            dry_run=dry_run,
            trace_writer=trace_writer,
            cycle=cycle,
        )
        if dry_run:
            return _result(
                SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
                before.observation,
                pause_result.after,
                gestures=0,
                cycles=1,
                dry_run=True,
                message="Dry run: the next cycle would pause before opening Manage Teams.",
            )
        gestures += pause_result.gestures_sent
        cycle += 1
        current = await observer.observe()
        _require_actionable(current)
    target = _target(current, "manage_teams_button")
    gesture = _click_gesture(
        current.observation,
        target,
        effect="open the Manage Teams management window",
    )
    if dry_run:
        _trace(
            trace_writer,
            SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
            cycle,
            current.observation,
            target_id=target.target_id,
            gesture=gesture,
            input_sent=False,
            verified=True,
            reason="dry run resolved one fresh anchored management target",
        )
        return _result(
            SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
            before.observation,
            current.observation,
            gestures=0,
            cycles=cycle,
            dry_run=True,
            message="Dry run: would click the current-frame Manage Teams target.",
        )
    semantic_before_click = _semantic_fingerprint(current.observation.semantic_after)
    observer.backend.execute(gesture, frame=current.observation.frame)
    gestures += 1
    try:
        after = await observer.observe()
    except Exception as error:
        _trace(
            trace_writer,
            SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
            cycle,
            current.observation,
            target_id=target.target_id,
            gesture=gesture,
            input_sent=True,
            verified=False,
            reason="post-click observation failed; no retry attempted",
        )
        raise SoftwareIncUIVerificationError(
            "Manage Teams click was sent but fresh verification failed; no retry attempted"
        ) from error
    _require_identity_continuity(current.observation, after.observation)
    if after.observation.scene not in _TEAM_MANAGEMENT_SCENES:
        first_after = after
        after = await observer.observe()
        _require_identity_continuity(first_after.observation, after.observation)
    semantic_after_click = _semantic_fingerprint(after.observation.semantic_after)
    if after.observation.scene not in _TEAM_MANAGEMENT_SCENES:
        _trace(
            trace_writer,
            SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
            cycle,
            after.observation,
            target_id=target.target_id,
            gesture=gesture,
            input_sent=True,
            verified=False,
            reason="fresh frame did not recognize Manage Teams; no retry attempted",
        )
        raise SoftwareIncUIVerificationError(
            "management click did not produce the verified Manage Teams scene; no retry attempted"
        )
    if semantic_before_click != semantic_after_click:
        raise SoftwareIncUIVerificationError(
            "opening Manage Teams changed gameplay semantics; no retry attempted"
        )
    _trace(
        trace_writer,
        SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
        cycle,
        after.observation,
        target_id=target.target_id,
        gesture=gesture,
        input_sent=True,
        verified=True,
        reason="Manage Teams recognized and gameplay semantics remained unchanged",
    )
    return _result(
        SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
        before.observation,
        after.observation,
        gestures=gestures,
        cycles=cycle,
        dry_run=False,
        message="Manage Teams opened through the visible UI and verified.",
    )


def _require_actionable(observed: ObservedSoftwareIncUI) -> None:
    observation = observed.observation
    if observation.modal_state is not ModalState.NONE:
        raise SoftwareIncUIObservationError(
            f"cannot act while modal state is {observation.modal_state.value}"
        )
    if observation.scene in {SoftwareIncUIScene.UNKNOWN, SoftwareIncUIScene.BLOCKING_MODAL}:
        raise SoftwareIncUIObservationError(f"cannot act from scene {observation.scene.value}")


def _target(observed: ObservedSoftwareIncUI, target_id: str) -> VisualTarget:
    matches = [target for target in observed.observation.targets if target.target_id == target_id]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(
            f"target {target_id!r} did not resolve exactly once in the fresh frame"
        )
    target = matches[0]
    if target.confidence < 0.8 or target.source_frame_id != observed.observation.frame.frame_id:
        raise SoftwareIncUIValidationError("resolved target is ambiguous or stale")
    if target.expires_at <= datetime.now(UTC):
        raise SoftwareIncUIValidationError("resolved target expired before gesture construction")
    return target


def _click_gesture(
    observation: SoftwareIncUIObservation, target: VisualTarget, *, effect: str
) -> InputGesture:
    if target.point is None:
        raise SoftwareIncUIValidationError("click target has no resolved current-frame point")
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


def _require_identity_continuity(
    before: SoftwareIncUIObservation, after: SoftwareIncUIObservation
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
        or before.frame.window_content_bounds != after.frame.window_content_bounds
        or before.frame.window_visible_regions != after.frame.window_visible_regions
        or before.frame.display_ids != after.frame.display_ids
    ):
        raise SoftwareIncUIVerificationError(
            "bridge, game, save, process, or window identity changed; no retry attempted"
        )


def _semantic_fingerprint(snapshot: GameSnapshot) -> str:
    payload = {
        "bridge_instance_id": snapshot.bridge_instance_id,
        "game_session_id": snapshot.game_session_id,
        "save_identity": snapshot.save_identity.model_dump(mode="json"),
        "game_state": snapshot.game_state,
        "surfaces": [
            surface.model_dump(mode="json")
            for surface in snapshot.surfaces
            if surface.coverage.surface not in {"office_ui", "staffing_ui"}
        ],
    }
    import json

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _trace(
    writer: Callable[[SoftwareIncUITraceRecord], object],
    action: SoftwareIncUIAction,
    cycle: int,
    observation: SoftwareIncUIObservation,
    *,
    target_id: str | None,
    gesture: InputGesture | None,
    input_sent: bool,
    verified: bool,
    reason: str,
) -> None:
    writer(
        SoftwareIncUITraceRecord(
            action=action,
            cycle=cycle,
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
    action: SoftwareIncUIAction,
    before: SoftwareIncUIObservation,
    after: SoftwareIncUIObservation,
    *,
    gestures: int,
    cycles: int,
    dry_run: bool,
    message: str,
    expected: tuple[str, ...] = (),
) -> SoftwareIncUIDoResult:
    return SoftwareIncUIDoResult(
        action=action,
        before=before,
        after=after,
        gestures_sent=gestures,
        cycles=cycles,
        dry_run=dry_run,
        verified=True,
        expected_differences=expected,
        message=message,
        completed_at=datetime.now(UTC),
    )


__all__ = ["execute_ui_action", "parse_ui_action"]
