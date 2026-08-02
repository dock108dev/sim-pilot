"""End-to-end state-machine tests for visible Software Inc. staffing control."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from sim_pilot.computer_control.backend import CapturedDesktopFrame
from sim_pilot.computer_control.models import (
    DesktopFrame,
    InputExecutionResult,
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
from sim_pilot.software_inc.errors import SoftwareIncUIVerificationError
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    VisualTarget,
)
from sim_pilot.software_inc.ui.observer import ObservedSoftwareIncUI
from sim_pilot.software_inc.ui.recognition import recognize_ui
from sim_pilot.software_inc.ui.staffing import parse_staffing_intent
from sim_pilot.software_inc.ui.staffing_controller import execute_staffing_intent

_SURFACES = (
    "applicants",
    "company",
    "contract_market",
    "contract_results",
    "contract_ui",
    "education",
    "education_ui",
    "employees",
    "finances",
    "game_state",
    "offices",
    "products",
    "staffing_ui",
    "teams",
    "work_items",
)


def _snapshot(
    sequence: int,
    *,
    scene: str,
    team_value: str = "",
    team_focused: bool = False,
    support_team: bool = False,
    role: str = "",
    wage_bracket: str = "",
) -> GameSnapshot:
    staffing_state = ObservedEntity(
        entity_type="staffing_ui_state",
        entity_id="current",
        values={
            "scene": scene,
            "team_name_value": team_value,
            "team_name_focused": team_focused,
            "selected_team": "",
            "selected_applicant_indices": "",
            "role": role,
            "wage_bracket": wage_bracket,
            "search_cost_text": "",
            "pool_text": "",
        },
    )
    teams = [
        ObservedEntity(
            entity_type="team",
            entity_id="core",
            values={"name": "Core", "employee_count": 1},
        )
    ]
    if support_team:
        teams.append(
            ObservedEntity(
                entity_type="team",
                entity_id="support",
                values={"name": "Support Alpha", "employee_count": 0},
            )
        )
    surfaces: list[ObservationSurface] = []
    for name in _SURFACES:
        entities: tuple[ObservedEntity, ...] = ()
        status = CoverageStatus.OBSERVED_COMPLETE
        if name == "staffing_ui":
            entities = (staffing_state,)
        elif name == "teams":
            entities = tuple(teams)
        elif name == "employees":
            entities = (
                ObservedEntity(
                    entity_type="employee",
                    entity_id="founder",
                    values={
                        "name": "Founder",
                        "role": "Founder",
                        "salary": 0.0,
                        "team": "Core",
                    },
                ),
            )
        elif name in {"finances", "offices", "products", "work_items"}:
            status = CoverageStatus.OBSERVED_PARTIAL
        surfaces.append(
            ObservationSurface(
                coverage=FieldCoverage(surface=name, status=status, fields=()),
                entities=entities,
            )
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
        surfaces=tuple(surfaces),
    )


def _observed(
    sequence: int,
    snapshot: GameSnapshot,
    scene: SoftwareIncUIScene,
    target_ids: tuple[str, ...],
) -> ObservedSoftwareIncUI:
    image = Image.new("RGB", (1200, 800), (80, 100, 120))
    digest = hashlib.sha256(image.tobytes() + str(sequence).encode()).hexdigest()
    bounds = WindowBounds(x=10, y=20, width=600, height=400)
    frame = DesktopFrame(
        frame_id=digest,
        capture_sequence=sequence,
        captured_at=datetime.now(UTC),
        process_id=77,
        window_id="window",
        window_title="Software Inc",
        window_bounds=bounds,
        window_frontmost=True,
        pixel_width=1200,
        pixel_height=800,
        display_scale=2.0,
        sha256=digest,
        platform="macos",
    )
    projection = hashlib.sha256(f"projection:{sequence}".encode()).hexdigest()
    targets = tuple(
        VisualTarget(
            target_id=target_id,
            source_frame_id=frame.frame_id,
            point=ScreenPoint(x=200, y=200),
            region=WindowBounds(x=180, y=180, width=40, height=40),
            scene=scene,
            projection_id=projection,
            confidence=0.95,
            evidence=("fixture target",),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        for target_id in target_ids
    )
    observation = SoftwareIncUIObservation(
        semantic_before=snapshot,
        semantic_after=snapshot,
        frame=frame,
        scene=scene,
        modal_state=ModalState.NONE,
        projection_id=projection,
        targets=targets,
        synchronization_started_at=datetime.now(UTC),
        synchronization_completed_at=datetime.now(UTC),
        synchronization_duration_seconds=0.01,
        semantic_capture_skew_seconds=0.01,
    )
    return ObservedSoftwareIncUI(observation, CapturedDesktopFrame(frame, image))


class _Backend:
    def __init__(self) -> None:
        self.gestures: list[InputGesture] = []

    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> InputExecutionResult:
        assert gesture.expected_frame_id == frame.frame_id
        self.gestures.append(gesture)
        return InputExecutionResult(gesture=gesture, sent_at=datetime.now(UTC))


class _Observer:
    def __init__(self, observations: list[ObservedSoftwareIncUI]) -> None:
        self.backend = _Backend()
        self._observations = observations

    async def observe(self) -> ObservedSoftwareIncUI:
        return self._observations.pop(0)


def test_staffing_target_requires_semantic_geometry_and_current_screenshot_pixels() -> None:
    snapshot = _snapshot(1, scene="create_team_form", team_focused=True)
    surfaces = list(snapshot.surfaces)
    staffing_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "staffing_ui"
    )
    state = surfaces[staffing_index].entities[0]
    target = ObservedEntity(
        entity_type="ui_target",
        entity_id="team_name_input",
        values={
            "x_ratio": 0.5,
            "y_ratio": 0.75,
            "width_ratio": 0.25,
            "height_ratio": 0.08,
            "interactable": True,
            "kind": "input",
            "label": "",
            "object_name": "TeamName",
            "path": "Canvas/TeamWindow/TeamName",
        },
    )
    add_target = ObservedEntity(
        entity_type="ui_target",
        entity_id="team-button-0",
        values={
            "x_ratio": 0.75,
            "y_ratio": 0.75,
            "width_ratio": 0.08,
            "height_ratio": 0.08,
            "interactable": True,
            "kind": "button",
            "label": "Add",
            "object_name": "Button",
            "path": "Canvas/TeamWindow/ContentPanel/Button",
        },
    )
    surfaces[staffing_index] = surfaces[staffing_index].model_copy(
        update={"entities": (state, target, add_target)}
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})
    capture = _observed(
        1,
        snapshot,
        SoftwareIncUIScene.CREATE_TEAM_FORM,
        (),
    ).capture
    letterboxed = Image.new("RGB", (1200, 800), (0, 0, 0))
    letterboxed.paste((80, 100, 120), (0, 100, 1200, 700))
    capture = CapturedDesktopFrame(capture.metadata, letterboxed)

    scene, _, _, targets = recognize_ui(capture, snapshot=snapshot, paused=True)

    assert scene is SoftwareIncUIScene.CREATE_TEAM_FORM
    assert [item.target_id for item in targets] == ["team_name_input", "commit_create_team"]
    assert targets[0].point == ScreenPoint(x=310, y=295)


def test_create_team_runs_one_gesture_per_fresh_cycle_and_verifies_delta() -> None:
    before = _snapshot(1, scene="manage_teams")
    form_empty = _snapshot(2, scene="create_team_form")
    form_focused = _snapshot(3, scene="create_team_form", team_focused=True)
    form_typed = _snapshot(
        4,
        scene="create_team_form",
        team_value="Support Alpha",
        team_focused=True,
    )
    form_revalidated = form_typed.model_copy(
        update={"bridge_sequence": 5, "capture_timestamp": datetime.now(UTC)}
    )
    after = _snapshot(6, scene="manage_teams", support_team=True)
    observer = _Observer(
        [
            _observed(1, before, SoftwareIncUIScene.MANAGE_TEAMS, ("open_create_team",)),
            _observed(2, form_empty, SoftwareIncUIScene.CREATE_TEAM_FORM, ("team_name_input",)),
            _observed(
                3,
                form_focused,
                SoftwareIncUIScene.CREATE_TEAM_FORM,
                ("team_name_input",),
            ),
            _observed(
                4,
                form_typed,
                SoftwareIncUIScene.CREATE_TEAM_FORM,
                ("commit_create_team",),
            ),
            _observed(
                5,
                form_revalidated,
                SoftwareIncUIScene.CREATE_TEAM_FORM,
                ("commit_create_team",),
            ),
            _observed(6, after, SoftwareIncUIScene.MANAGE_TEAMS, ()),
        ]
    )

    result = asyncio.run(
        execute_staffing_intent(
            parse_staffing_intent("create a team named Support Alpha"),
            approval_provider=lambda _plan, _approval: True,
            observer_factory=lambda: observer,  # type: ignore[arg-type,return-value]
            trace_writer=lambda _record: None,
        )
    )

    assert result.verified
    assert result.gestures_sent == 4
    assert [gesture.target_id for gesture in observer.backend.gestures] == [
        "open_create_team",
        "team_name_input",
        "team_name_input",
        "commit_create_team",
    ]


def test_create_team_does_not_retry_an_ineffective_manage_teams_click() -> None:
    paused = _snapshot(1, scene="gameplay")
    still_paused = paused.model_copy(
        update={"bridge_sequence": 2, "capture_timestamp": datetime.now(UTC)}
    )
    observer = _Observer(
        [
            _observed(
                1,
                paused,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                ("manage_teams_button",),
            ),
            _observed(
                2,
                still_paused,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                ("manage_teams_button",),
            ),
        ]
    )

    with pytest.raises(SoftwareIncUIVerificationError, match="no retry attempted"):
        asyncio.run(
            execute_staffing_intent(
                parse_staffing_intent("create a team named Support Alpha"),
                approval_provider=lambda _plan, _approval: True,
                observer_factory=lambda: observer,  # type: ignore[arg-type,return-value]
                trace_writer=lambda _record: None,
            )
        )

    assert [gesture.target_id for gesture in observer.backend.gestures] == ["manage_teams_button"]


def test_create_team_does_not_retry_an_ineffective_field_focus_click() -> None:
    form = _snapshot(1, scene="create_team_form")
    still_unfocused = form.model_copy(
        update={"bridge_sequence": 2, "capture_timestamp": datetime.now(UTC)}
    )
    observer = _Observer(
        [
            _observed(
                1,
                form,
                SoftwareIncUIScene.CREATE_TEAM_FORM,
                ("team_name_input",),
            ),
            _observed(
                2,
                still_unfocused,
                SoftwareIncUIScene.CREATE_TEAM_FORM,
                ("team_name_input",),
            ),
        ]
    )

    with pytest.raises(SoftwareIncUIVerificationError, match="did not focus.*no retry"):
        asyncio.run(
            execute_staffing_intent(
                parse_staffing_intent("create a team named Support Alpha"),
                approval_provider=lambda _plan, _approval: True,
                observer_factory=lambda: observer,  # type: ignore[arg-type,return-value]
                trace_writer=lambda _record: None,
            )
        )

    assert [gesture.target_id for gesture in observer.backend.gestures] == ["team_name_input"]


def test_hiring_does_not_retry_an_ineffective_role_combo_click() -> None:
    setup = _snapshot(
        1,
        scene="hiring_setup",
        support_team=True,
        role="Lead",
        wage_bracket="Low",
    )
    unchanged = setup.model_copy(
        update={"bridge_sequence": 2, "capture_timestamp": datetime.now(UTC)}
    )
    observer = _Observer(
        [
            _observed(
                1,
                setup,
                SoftwareIncUIScene.HIRING_SETUP,
                ("role_combo",),
            ),
            _observed(
                2,
                unchanged,
                SoftwareIncUIScene.HIRING_SETUP,
                ("role_combo",),
            ),
        ]
    )

    with pytest.raises(SoftwareIncUIVerificationError, match="no retry attempted"):
        asyncio.run(
            execute_staffing_intent(
                parse_staffing_intent(
                    "hire one programmer for Support Alpha for no more than $8,000 per month"
                ),
                approval_provider=lambda _plan, _approval: True,
                observer_factory=lambda: observer,  # type: ignore[arg-type,return-value]
                trace_writer=lambda _record: None,
            )
        )

    assert [gesture.target_id for gesture in observer.backend.gestures] == ["role_combo"]
