from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from PIL import Image

from sim_pilot.computer_control.backend import CapturedDesktopFrame
from sim_pilot.computer_control.models import (
    DesktopFrame,
    InputGesture,
    ScreenPoint,
    WindowBounds,
)
from sim_pilot.game_bridge import (
    Architecture,
    CoverageStatus,
    FieldCoverage,
    GameSnapshot,
    Identity,
    IdentityStatus,
    ObservationSurface,
    ObservedEntity,
    Platform,
)
from sim_pilot.software_inc.errors import (
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    StaffingTraceRecord,
    VisualTarget,
)
from sim_pilot.software_inc.ui.observer import ObservedSoftwareIncUI
from sim_pilot.software_inc.ui.workstation import (
    WorkstationPlan,
    build_workstation_plan,
    parse_workstation_intent,
    require_valid_workstation_approval,
    resolve_workstation_approval,
    verify_workstation_result,
)
from sim_pilot.software_inc.ui.workstation_controller import execute_workstation_intent


def _surface(name: str, *entities: ObservedEntity) -> ObservationSurface:
    return ObservationSurface(
        coverage=FieldCoverage(
            surface=name,
            status=(
                CoverageStatus.OBSERVED_PARTIAL
                if name == "finances"
                else CoverageStatus.OBSERVED_COMPLETE
            ),
            fields=(),
        ),
        entities=tuple(sorted(entities, key=lambda item: (item.entity_type, item.entity_id))),
    )


def _catalog(
    identity: str,
    name: str,
    furniture_type: str,
    cost: int,
    *,
    can_assign: bool = False,
    needs_chair: bool = False,
    snaps_to: str = "",
    snap_points: str = "",
    wattage: int = 0,
) -> ObservedEntity:
    return ObservedEntity(
        entity_type="furniture_catalog_item",
        entity_id=identity,
        values={
            "auto_place_groups": "",
            "can_assign": can_assign,
            "can_not_snap": False,
            "can_rotate": True,
            "categories": "Office",
            "computer_power": 1 if furniture_type == "Computer" else 0,
            "construction": False,
            "display_name": name,
            "function_category": "Work",
            "in_rent_mode": True,
            "inventory_count": 0,
            "is_snapping": bool(snaps_to),
            "needs_chair": needs_chair,
            "one_time_cost": cost,
            "prefab_name": identity.split(":", maxsplit=1)[0],
            "search_enabled": True,
            "search_title": name,
            "searchable": True,
            "snap_points": snap_points,
            "snaps_to": snaps_to,
            "type": furniture_type,
            "valid_indoors": True,
            "valid_outdoors": False,
            "wattage": wattage,
        },
    )


def _snapshot(
    *,
    sequence: int = 2,
    cash: int = 50_000,
    room_teams: str = "",
    valid_workstations: int = 0,
    room_major_problem: bool = False,
    equipment: tuple[ObservedEntity, ...] = (),
) -> GameSnapshot:
    surfaces = (
        _surface(
            "build_catalog",
            _catalog(
                "Cheap Desk:0",
                "Cheap Desk",
                "Desk",
                100,
                snap_points="AtTable|OnTable",
            ),
            _catalog(
                "Modern Computer:0",
                "Modern Computer",
                "Computer",
                500,
                can_assign=True,
                needs_chair=True,
                snaps_to="OnTable",
                wattage=25,
            ),
            _catalog(
                "Office Chair:0",
                "Office Chair",
                "Chair",
                50,
                snaps_to="AtTable",
            ),
            _catalog("Trash Can:0", "Trash Can", "Trashcan", 20),
        ),
        _surface(
            "build_ui",
            ObservedEntity(
                entity_type="build_ui_state",
                entity_id="current",
                values={"scene": "gameplay"},
            ),
        ),
        _surface(
            "finances",
            ObservedEntity(
                entity_type="company_finances",
                entity_id="1",
                values={"cash": cash},
            ),
        ),
        _surface(
            "offices",
            ObservedEntity(
                entity_type="office_room",
                entity_id="3",
                values={
                    "area": 48,
                    "assigned_teams": room_teams,
                    "major_problem": room_major_problem,
                    "problem_count": 1 if room_major_problem else 0,
                    "valid_workstations": valid_workstations,
                },
            ),
            *equipment,
        ),
        _surface(
            "teams",
            ObservedEntity(
                entity_type="team",
                entity_id="Core",
                values={"name": "Core", "employee_count": 1},
            ),
        ),
    )
    return GameSnapshot(
        capture_timestamp=datetime.now(UTC),
        capture_started_marker="main-thread",
        capture_completed_marker="main-thread",
        bridge_sequence=sequence,
        bridge_instance_id="bridge",
        game_session_id="session",
        game_id="software-inc",
        game_version="1.8.41",
        adapter_version="software-inc-readonly-v5",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        map_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="not exposed"),
        save_identity=Identity(status=IdentityStatus.OBSERVED, value="disposable"),
        game_state={"force_pause": True, "simulation_speed": "0"},
        surfaces=surfaces,
    )


def _observation(snapshot: GameSnapshot) -> SoftwareIncUIObservation:
    now = datetime.now(UTC)
    return SoftwareIncUIObservation(
        semantic_before=snapshot,
        semantic_after=snapshot,
        frame=DesktopFrame(
            frame_id="a" * 64,
            capture_sequence=1,
            captured_at=now,
            process_id=10,
            window_id="20",
            window_title="Software Inc",
            window_bounds=WindowBounds(x=0, y=30, width=1920, height=1050),
            window_frontmost=True,
            pixel_width=1920,
            pixel_height=1050,
            display_scale=1,
            sha256="b" * 64,
            platform="macos",
        ),
        scene=SoftwareIncUIScene.GAMEPLAY_PAUSED,
        modal_state=ModalState.NONE,
        projection_id="c" * 64,
        targets=(),
        synchronization_started_at=now,
        synchronization_completed_at=now,
        synchronization_duration_seconds=0,
        semantic_capture_skew_seconds=0,
    )


def _snapshot_with_build_state(
    snapshot: GameSnapshot,
    *,
    scene: str,
    builder_prefab_name: str = "",
    builder_cost: int = 0,
    builder_room_id: str = "",
    preview_valid: bool = False,
) -> GameSnapshot:
    state = ObservedEntity(
        entity_type="build_ui_state",
        entity_id="current",
        values={
            "builder_cost": builder_cost,
            "builder_prefab_name": builder_prefab_name,
            "builder_room_id": builder_room_id,
            "preview_valid": preview_valid,
            "scene": scene,
        },
    )
    return snapshot.model_copy(
        update={
            "surfaces": tuple(
                surface.model_copy(update={"entities": (state,)})
                if surface.coverage.surface == "build_ui"
                else surface
                for surface in snapshot.surfaces
            )
        }
    )


def _observed_ui(
    snapshot: GameSnapshot,
    *,
    scene: SoftwareIncUIScene,
    marker: str,
    target_ids: tuple[str, ...] = (),
) -> ObservedSoftwareIncUI:
    base = _observation(snapshot)
    frame = base.frame.model_copy(
        update={"frame_id": marker * 64, "capture_sequence": snapshot.bridge_sequence}
    )
    projection_id = marker[::-1] * 64
    targets = tuple(
        VisualTarget(
            target_id=target_id,
            source_frame_id=frame.frame_id,
            point=ScreenPoint(x=500 + index * 20, y=400 + index * 20),
            scene=scene,
            projection_id=projection_id,
            confidence=0.99,
            evidence=("fresh exact semantic target",),
            expires_at=datetime.now(UTC) + timedelta(seconds=30),
        )
        for index, target_id in enumerate(target_ids)
    )
    observation = base.model_copy(
        update={
            "frame": frame,
            "scene": scene,
            "projection_id": projection_id,
            "targets": targets,
        }
    )
    return ObservedSoftwareIncUI(
        observation,
        CapturedDesktopFrame(frame, Image.new("RGB", (1920, 1050), (40, 50, 60))),
    )


def test_plans_exact_cheapest_compatible_bundle_and_cash() -> None:
    intent = parse_workstation_intent(
        "prepare one workstation for Core while keeping $49,000 in reserve"
    )
    plan = build_workstation_plan(intent, _observation(_snapshot()))

    assert plan.room_id == "3"
    assert plan.assign_room_to_team is True
    assert [line.purpose for line in plan.line_items] == [
        "work_surface",
        "computer",
        "chair",
    ]
    assert plan.total_one_time_cost == Decimal("650")
    assert plan.projected_cash_after == Decimal("49350.00")
    assert plan.observed_variable_wattage == Decimal("25")
    assert plan.fixed_recurring_monthly_cost == 0


def test_rejects_reserve_violation_before_approval_or_input() -> None:
    intent = parse_workstation_intent(
        "prepare one workstation for Core while keeping $50,000 in reserve"
    )

    with pytest.raises(SoftwareIncUIValidationError, match="below the requested"):
        build_workstation_plan(intent, _observation(_snapshot()))


def test_approval_is_bound_to_catalog_cash_session_and_save() -> None:
    observation = _observation(_snapshot())
    plan = build_workstation_plan(
        parse_workstation_intent("place a workstation for Core"), observation
    )
    approval = resolve_workstation_approval(plan, approved=True)

    require_valid_workstation_approval(plan, approval, observation)
    changed_cash = _observation(_snapshot(cash=49_000))
    with pytest.raises(SoftwareIncUIValidationError, match="cash changed"):
        require_valid_workstation_approval(plan, approval, changed_cash)


def test_approval_fingerprint_changes_after_room_assignment() -> None:
    intent = parse_workstation_intent("place a workstation for Core")
    unassigned = build_workstation_plan(intent, _observation(_snapshot()))
    assigned = build_workstation_plan(
        intent,
        _observation(_snapshot(sequence=3, room_teams="Core")),
    )

    assert unassigned.assign_room_to_team is True
    assert assigned.assign_room_to_team is False
    assert unassigned.fingerprint != assigned.fingerprint


def test_existing_valid_workstation_prevents_duplicate_even_with_room_problem() -> None:
    plan = build_workstation_plan(
        parse_workstation_intent(
            "prepare one workstation for Core while keeping $48,000 in reserve"
        ),
        _observation(
            _snapshot(
                cash=48_360,
                room_teams="Core",
                valid_workstations=1,
                room_major_problem=True,
            )
        ),
    )

    assert plan.room_id == "3"
    assert plan.line_items == ()
    assert plan.total_one_time_cost == 0
    assert plan.projected_cash_after == Decimal("48360.00")


def test_existing_computer_room_plans_exact_trash_capacity_correction() -> None:
    computer = ObservedEntity(
        entity_type="office_equipment",
        entity_id="computer-1",
        values={
            "function_category": "Computer",
            "prefab_name": "Modern Computer",
            "room_id": "3",
            "type": "Computer",
        },
    )
    plan = build_workstation_plan(
        parse_workstation_intent(
            "prepare one workstation for Core while keeping $48,000 in reserve"
        ),
        _observation(
            _snapshot(
                cash=51_310,
                room_teams="Core",
                valid_workstations=1,
                room_major_problem=True,
                equipment=(computer,),
            )
        ),
    )

    assert [line.purpose for line in plan.line_items] == ["trashcan"]
    assert plan.line_items[0].catalog_item.prefab_name == "Trash Can"
    assert plan.expected_room_problem_cleared
    assert plan.total_one_time_cost == Decimal("20")
    assert plan.projected_cash_after == Decimal("51290.00")


def test_trash_capacity_correction_requires_problem_to_clear() -> None:
    computer = ObservedEntity(
        entity_type="office_equipment",
        entity_id="computer-1",
        values={
            "function_category": "Computer",
            "prefab_name": "Modern Computer",
            "room_id": "3",
            "type": "Computer",
        },
    )
    before = _snapshot(
        cash=51_310,
        room_teams="Core",
        valid_workstations=1,
        room_major_problem=True,
        equipment=(computer,),
    )
    plan = build_workstation_plan(
        parse_workstation_intent("prepare one workstation for Core"),
        _observation(before),
    )
    still_broken = _snapshot(
        sequence=20,
        cash=51_290,
        room_teams="Core",
        valid_workstations=1,
        room_major_problem=True,
        equipment=(computer,),
    )

    with pytest.raises(SoftwareIncUIVerificationError, match="did not clear"):
        verify_workstation_result(before, still_broken, plan)

    corrected = _snapshot(
        sequence=21,
        cash=51_290,
        room_teams="Core",
        valid_workstations=1,
        equipment=(computer,),
    )
    verify_workstation_result(before, corrected, plan)


def test_existing_valid_workstation_completes_without_approval_or_input() -> None:
    observation = _observation(
        _snapshot(
            cash=48_360,
            room_teams="Core",
            valid_workstations=1,
            room_major_problem=True,
        )
    )
    observed = ObservedSoftwareIncUI(
        observation,
        CapturedDesktopFrame(
            observation.frame,
            Image.new("RGB", (1920, 1050), (40, 50, 60)),
        ),
    )

    class Backend:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("existing capacity must not send input")

    class Observer:
        backend = Backend()

        async def observe(self) -> ObservedSoftwareIncUI:
            return observed

    result = asyncio.run(
        execute_workstation_intent(
            parse_workstation_intent("prepare one workstation for Core"),
            approval_provider=lambda _plan: (_ for _ in ()).throw(
                AssertionError("existing capacity must not request approval")
            ),
            observer_factory=Observer,  # type: ignore[arg-type]
            trace_writer=lambda _record: (_ for _ in ()).throw(
                AssertionError("existing capacity must not write an input trace")
            ),
        )
    )

    assert result.verified
    assert result.gestures_sent == 0
    assert result.approval is None
    assert "already has a verified valid workstation" in result.message


def test_verifies_exact_room_capacity_assignment_and_cash_delta() -> None:
    before = _snapshot()
    plan = build_workstation_plan(
        parse_workstation_intent("prepare one workstation for Core"), _observation(before)
    )
    after = _snapshot(
        sequence=20,
        cash=49_350,
        room_teams="Core",
        valid_workstations=1,
    )

    verify_workstation_result(before, after, plan)


def test_resumes_an_interrupted_bundle_without_duplicate_purchase() -> None:
    existing_desk = ObservedEntity(
        entity_type="office_equipment",
        entity_id="desk-1",
        values={
            "blocked": False,
            "prefab_name": "Cheap Desk",
            "room_id": "3",
            "valid": True,
        },
    )
    plan = build_workstation_plan(
        parse_workstation_intent("prepare one workstation for Core"),
        _observation(_snapshot(equipment=(existing_desk,))),
    )

    assert [(item.purpose, item.equipment_id) for item in plan.reused_components] == [
        ("work_surface", "desk-1")
    ]
    assert [line.purpose for line in plan.line_items] == ["computer", "chair"]
    assert plan.total_one_time_cost == Decimal("550")


@pytest.mark.parametrize("dry_run,approve", ((True, True), (False, False)))
def test_dry_run_and_denied_approval_send_zero_input(dry_run: bool, approve: bool) -> None:
    observation = _observation(_snapshot())
    observed = ObservedSoftwareIncUI(
        observation,
        CapturedDesktopFrame(
            observation.frame,
            Image.new("RGB", (1920, 1050), (40, 50, 60)),
        ),
    )

    class Backend:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("no input may be sent")

    class Observer:
        backend = Backend()

        async def observe(self) -> ObservedSoftwareIncUI:
            return observed

    result = asyncio.run(
        execute_workstation_intent(
            parse_workstation_intent("prepare one workstation for Core"),
            dry_run=dry_run,
            approval_provider=(lambda _plan: approve) if not dry_run else None,
            observer_factory=Observer,  # type: ignore[arg-type]
            trace_writer=lambda _record: (_ for _ in ()).throw(
                AssertionError("no trace may be written without input")
            ),
        )
    )

    assert result.gestures_sent == 0
    assert result.verified is False
    assert result.dry_run is dry_run


def test_contract_browser_is_closed_and_plan_is_refreshed_before_approval() -> None:
    contract_snapshot = _snapshot(sequence=2)
    paused_snapshot = _snapshot(sequence=3)
    contract_base = _observation(contract_snapshot)
    contract_target = VisualTarget(
        target_id="close_contract_browser",
        source_frame_id=contract_base.frame.frame_id,
        point=ScreenPoint(x=1400, y=150),
        scene=SoftwareIncUIScene.CONTRACT_BROWSER,
        projection_id=contract_base.projection_id,
        confidence=0.99,
        evidence=("exact contract close control",),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    contract_observation = contract_base.model_copy(
        update={
            "scene": SoftwareIncUIScene.CONTRACT_BROWSER,
            "targets": (contract_target,),
        }
    )
    paused_observation = _observation(paused_snapshot).model_copy(
        update={
            "frame": _observation(paused_snapshot).frame.model_copy(
                update={"frame_id": "d" * 64, "capture_sequence": 2}
            ),
            "scene": SoftwareIncUIScene.GAMEPLAY_PAUSED,
            "projection_id": "e" * 64,
        }
    )
    observations = iter(
        (
            ObservedSoftwareIncUI(
                contract_observation,
                CapturedDesktopFrame(
                    contract_observation.frame,
                    Image.new("RGB", (1920, 1050), (40, 50, 60)),
                ),
            ),
            ObservedSoftwareIncUI(
                paused_observation,
                CapturedDesktopFrame(
                    paused_observation.frame,
                    Image.new("RGB", (1920, 1050), (40, 50, 60)),
                ),
            ),
        )
    )
    gestures: list[InputGesture] = []
    traces: list[StaffingTraceRecord] = []
    approved_plans: list[WorkstationPlan] = []

    def deny_after_recording(plan: WorkstationPlan) -> bool:
        approved_plans.append(plan)
        return False

    class Backend:
        def execute(self, gesture: InputGesture, **_kwargs: object) -> None:
            gestures.append(gesture)

    class Observer:
        backend = Backend()

        async def observe(self) -> ObservedSoftwareIncUI:
            return next(observations)

    result = asyncio.run(
        execute_workstation_intent(
            parse_workstation_intent("prepare one workstation for Core"),
            approval_provider=deny_after_recording,
            observer_factory=Observer,  # type: ignore[arg-type]
            trace_writer=traces.append,
        )
    )

    assert [gesture.target_id for gesture in gestures] == ["close_contract_browser"]
    assert approved_plans[0].source_bridge_sequence == 3
    assert approved_plans[0].source_frame_id == "d" * 64
    assert result.approval is not None and not result.approval.approved
    assert result.gestures_sent == 1
    assert traces[0].plan_fingerprint is None
    assert traces[0].approval_id is None


def test_pause_menu_is_closed_and_game_is_repaused_before_approval() -> None:
    def observed(
        sequence: int,
        scene: SoftwareIncUIScene,
        target_id: str | None,
        frame_marker: str,
    ) -> ObservedSoftwareIncUI:
        snapshot = _snapshot(sequence=sequence)
        if scene is SoftwareIncUIScene.GAMEPLAY_RUNNING:
            snapshot = snapshot.model_copy(
                update={"game_state": {"force_pause": False, "simulation_speed": "1"}}
            )
        base = _observation(snapshot)
        frame = base.frame.model_copy(
            update={"frame_id": frame_marker * 64, "capture_sequence": sequence}
        )
        projection_id = chr(ord(frame_marker) + 1) * 64
        targets = ()
        if target_id is not None:
            targets = (
                VisualTarget(
                    target_id=target_id,
                    source_frame_id=frame.frame_id,
                    point=ScreenPoint(x=500, y=400),
                    scene=scene,
                    projection_id=projection_id,
                    confidence=0.99,
                    evidence=("fixture",),
                    expires_at=datetime.now(UTC) + timedelta(seconds=30),
                ),
            )
        observation = base.model_copy(
            update={
                "frame": frame,
                "scene": scene,
                "modal_state": (
                    ModalState.BLOCKING
                    if scene is SoftwareIncUIScene.PAUSE_MENU
                    else ModalState.NONE
                ),
                "projection_id": projection_id,
                "targets": targets,
            }
        )
        return ObservedSoftwareIncUI(
            observation,
            CapturedDesktopFrame(frame, Image.new("RGB", (1920, 1050), (40, 50, 60))),
        )

    observations = iter(
        (
            observed(2, SoftwareIncUIScene.PAUSE_MENU, "close_pause_menu", "a"),
            observed(3, SoftwareIncUIScene.GAMEPLAY_RUNNING, "pause_button", "c"),
            observed(4, SoftwareIncUIScene.GAMEPLAY_PAUSED, None, "e"),
        )
    )
    gestures: list[InputGesture] = []

    class Backend:
        def execute(self, gesture: InputGesture, **_kwargs: object) -> None:
            gestures.append(gesture)

    class Observer:
        backend = Backend()

        async def observe(self) -> ObservedSoftwareIncUI:
            return next(observations)

    result = asyncio.run(
        execute_workstation_intent(
            parse_workstation_intent("prepare one workstation for Core"),
            approval_provider=lambda _plan: False,
            observer_factory=Observer,  # type: ignore[arg-type]
            trace_writer=lambda _record: None,
        )
    )

    assert [gesture.target_id for gesture in gestures] == [
        "close_pause_menu",
        "pause_button",
    ]
    assert result.gestures_sent == 2
    assert result.approval is not None and not result.approval.approved


def test_approved_workstation_uses_a_fresh_post_prompt_target() -> None:
    initial_snapshot = _snapshot(sequence=2)
    refreshed_snapshot = _snapshot(sequence=3)
    initial_observation = _observation(initial_snapshot)
    refreshed_frame = initial_observation.frame.model_copy(
        update={"frame_id": "d" * 64, "capture_sequence": 2}
    )
    fresh_target = VisualTarget(
        target_id="room_candidate_3_0",
        source_frame_id=refreshed_frame.frame_id,
        point=ScreenPoint(x=500, y=400),
        scene=SoftwareIncUIScene.GAMEPLAY_PAUSED,
        projection_id="e" * 64,
        confidence=0.99,
        evidence=("fresh post-approval frame",),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    refreshed_observation = _observation(refreshed_snapshot).model_copy(
        update={
            "frame": refreshed_frame,
            "projection_id": "e" * 64,
            "targets": (fresh_target,),
        }
    )
    observations = iter(
        (
            ObservedSoftwareIncUI(
                initial_observation,
                CapturedDesktopFrame(
                    initial_observation.frame,
                    Image.new("RGB", (1920, 1050), (40, 50, 60)),
                ),
            ),
            ObservedSoftwareIncUI(
                refreshed_observation,
                CapturedDesktopFrame(
                    refreshed_observation.frame,
                    Image.new("RGB", (1920, 1050), (40, 50, 60)),
                ),
            ),
        )
    )
    gestures: list[InputGesture] = []

    class ExpectedStop(RuntimeError):
        pass

    class Backend:
        def execute(self, gesture: InputGesture, **_kwargs: object) -> None:
            gestures.append(gesture)
            raise ExpectedStop

    class Observer:
        backend = Backend()

        async def observe(self) -> ObservedSoftwareIncUI:
            return next(observations)

    with pytest.raises(ExpectedStop):
        asyncio.run(
            execute_workstation_intent(
                parse_workstation_intent("prepare one workstation for Core"),
                approval_provider=lambda _plan: True,
                observer_factory=Observer,  # type: ignore[arg-type]
                trace_writer=lambda _record: None,
            )
        )

    assert len(gestures) == 1
    assert gestures[0].target_id == "room_candidate_3_0"
    assert gestures[0].expected_frame_id == "d" * 64


def test_furniture_is_moved_to_a_fresh_room_target_before_placement_click() -> None:
    initial = _observed_ui(
        _snapshot(sequence=2, room_teams="Core"),
        scene=SoftwareIncUIScene.GAMEPLAY_PAUSED,
        marker="a",
    )
    refreshed = _observed_ui(
        _snapshot(sequence=3, room_teams="Core"),
        scene=SoftwareIncUIScene.GAMEPLAY_PAUSED,
        marker="b",
        target_ids=("open_build_mode",),
    )
    build_mode = _observed_ui(
        _snapshot_with_build_state(_snapshot(sequence=4, room_teams="Core"), scene="build_mode"),
        scene=SoftwareIncUIScene.BUILD_MODE,
        marker="c",
        target_ids=("build_catalog_item:Cheap Desk",),
    )
    initial_preview = _observed_ui(
        _snapshot_with_build_state(
            _snapshot(sequence=5, room_teams="Core"),
            scene="furniture_placement",
            builder_prefab_name="Cheap Desk",
            builder_cost=100,
            builder_room_id="3",
            preview_valid=True,
        ),
        scene=SoftwareIncUIScene.FURNITURE_PLACEMENT,
        marker="d",
        target_ids=("room_candidate_3_0", "open_build_mode"),
    )
    moved_preview = _observed_ui(
        _snapshot_with_build_state(
            _snapshot(sequence=6, room_teams="Core"),
            scene="furniture_placement",
            builder_prefab_name="Cheap Desk",
            builder_cost=100,
            builder_room_id="3",
            preview_valid=True,
        ),
        scene=SoftwareIncUIScene.FURNITURE_PLACEMENT,
        marker="e",
        target_ids=("room_candidate_3_0", "open_build_mode"),
    )
    desk = ObservedEntity(
        entity_type="office_equipment",
        entity_id="desk-new",
        values={
            "blocked": False,
            "prefab_name": "Cheap Desk",
            "room_id": "3",
            "valid": True,
        },
    )
    placed = _observed_ui(
        _snapshot_with_build_state(
            _snapshot(
                sequence=7,
                cash=49_900,
                room_teams="Core",
                equipment=(desk,),
            ),
            scene="furniture_placement",
            builder_prefab_name="Cheap Desk",
            builder_cost=100,
            builder_room_id="3",
            preview_valid=True,
        ),
        scene=SoftwareIncUIScene.FURNITURE_PLACEMENT,
        marker="f",
        target_ids=("room_candidate_3_0", "open_build_mode"),
    )
    observations = iter((initial, refreshed, build_mode, initial_preview, moved_preview, placed))
    gestures: list[InputGesture] = []

    class ExpectedStop(RuntimeError):
        pass

    class Backend:
        def execute(self, gesture: InputGesture, **_kwargs: object) -> None:
            gestures.append(gesture)
            if gesture.target_id == "stop_multiple_placement":
                raise ExpectedStop

    class Observer:
        backend = Backend()

        async def observe(self) -> ObservedSoftwareIncUI:
            return next(observations)

    with pytest.raises(ExpectedStop):
        asyncio.run(
            execute_workstation_intent(
                parse_workstation_intent("prepare one workstation for Core"),
                approval_provider=lambda _plan: True,
                observer_factory=Observer,  # type: ignore[arg-type]
                trace_writer=lambda _record: None,
            )
        )

    assert [(gesture.kind.value, gesture.target_id) for gesture in gestures] == [
        ("click", "open_build_mode"),
        ("click", "build_catalog_item:Cheap Desk"),
        ("move", "room_candidate_3_0"),
        ("click", "room_candidate_3_0"),
        ("click", "stop_multiple_placement"),
    ]
