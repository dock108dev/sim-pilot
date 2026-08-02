"""Software Inc. visual recognition and one-gesture UI-cycle behavior."""

from __future__ import annotations

import asyncio
import hashlib
import stat
from datetime import UTC, datetime, timedelta
from math import isclose
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from sim_pilot.computer_control.backend import CapturedDesktopFrame
from sim_pilot.computer_control.errors import ComputerControlError, StaleDesktopFrameError
from sim_pilot.computer_control.models import (
    DesktopFrame,
    InputExecutionResult,
    InputGesture,
    ScreenPoint,
    WindowBounds,
)
from sim_pilot.game_bridge.models import (
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
from sim_pilot.software_inc.errors import SoftwareIncUIObservationError
from sim_pilot.software_inc.ui.controller import execute_ui_action, parse_ui_action
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIAction,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    SoftwareIncUITraceRecord,
    VisualTarget,
)
from sim_pilot.software_inc.ui.observer import (
    ObservedSoftwareIncUI,
    capture_with_retry,
    require_ui_continuity,
)
from sim_pilot.software_inc.ui.recognition import (
    _active_viewport_bounds,  # pyright: ignore[reportPrivateUsage]
    _macos_unity_content_bounds,  # pyright: ignore[reportPrivateUsage]
    _semantic_viewport_bounds,  # pyright: ignore[reportPrivateUsage]
    _synthetic_product_combo_entities,  # pyright: ignore[reportPrivateUsage]
    known_nonblocking_help_tip,
    recognize_ui,
    semantic_blocking_dialog,
)
from sim_pilot.software_inc.ui.trace import append_ui_trace

_SURFACES = (
    "applicants",
    "build_catalog",
    "build_ui",
    "company",
    "contract_market",
    "contract_results",
    "contract_ui",
    "education",
    "education_ui",
    "employees",
    "finances",
    "game_state",
    "infrastructure",
    "office_ui",
    "offices",
    "product_catalog",
    "product_ui",
    "products",
    "staffing_ui",
    "teams",
    "work_items",
)


def _snapshot(sequence: int, *, paused: bool) -> GameSnapshot:
    surfaces = tuple(
        ObservationSurface(
            coverage=FieldCoverage(
                surface=name,
                status=(
                    CoverageStatus.OBSERVED_PARTIAL
                    if name in {"finances", "products"}
                    else CoverageStatus.OBSERVED_COMPLETE
                ),
                fields=(),
            )
        )
        for name in _SURFACES
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
        map_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="unavailable"),
        save_identity=Identity(status=IdentityStatus.OBSERVED, value="test-save"),
        game_state={"force_pause": paused, "simulation_speed": "0" if paused else "1"},
        surfaces=surfaces,
    )


def _image(
    *,
    management: bool = False,
    modal: bool = False,
    time_x: int = 545,
    time_y: int = 135,
    time_width: int = 22,
) -> Image.Image:
    image = Image.new("RGB", (1200, 800), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((1, 120, 1198, 680), fill=(48, 58, 68), outline=(50, 220, 75), width=3)
    for row in range(8):
        for column in range(12):
            red = 35 + (row * 17 + column * 11) % 150
            green = 40 + (row * 23 + column * 7) % 145
            blue = 45 + (row * 13 + column * 19) % 140
            draw.rectangle(
                (column * 100 + 5, row * 65 + 125, column * 100 + 98, row * 65 + 188),
                fill=(red, green, blue),
            )
    draw.rectangle((time_x, time_y, time_x + time_width, time_y + 43), fill=(55, 165, 65))
    first_bar = time_x + round(time_width * 0.32)
    second_bar = time_x + round(time_width * 0.64)
    draw.rectangle(
        (first_bar, time_y + 10, first_bar + 3, time_y + 33),
        fill=(235, 235, 235),
    )
    draw.rectangle(
        (second_bar, time_y + 10, second_bar + 3, time_y + 33),
        fill=(235, 235, 235),
    )
    draw.rectangle((48, 584, 300, 688), fill=(178, 178, 178))
    draw.ellipse((140, 658, 170, 688), fill=(220, 220, 220))
    draw.rectangle((151, 664, 159, 684), fill=(30, 30, 30))
    draw.rectangle((145, 670, 165, 679), fill=(30, 30, 30))
    draw.ellipse((122, 658, 146, 688), fill=(220, 220, 220))
    draw.rectangle((130, 664, 138, 684), fill=(30, 30, 30))
    if management:
        draw.rectangle((300, 180, 900, 600), fill=(185, 185, 185))
        draw.rectangle((300, 180, 900, 230), fill=(35, 125, 130))
        draw.rectangle((865, 187, 892, 214), fill=(190, 35, 35))
    if modal:
        draw.rectangle((360, 240, 840, 560), fill=(45, 60, 110))
    return image


def capture_fixture(image: Image.Image, *, sequence: int = 1) -> CapturedDesktopFrame:
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    frame = DesktopFrame(
        frame_id=hashlib.sha256(f"frame:{sequence}:{digest}".encode()).hexdigest(),
        capture_sequence=sequence,
        captured_at=datetime.now(UTC),
        process_id=77,
        window_id="42",
        window_title="Software Inc",
        window_bounds=WindowBounds(x=0, y=33, width=600, height=400),
        window_frontmost=True,
        pixel_width=1200,
        pixel_height=800,
        display_scale=2.0,
        sha256=digest,
        platform="macos",
    )
    return CapturedDesktopFrame(frame, image)


def test_macos_decorated_unity_window_excludes_exact_title_bar() -> None:
    image = Image.new("RGB", (960, 568), (238, 238, 238))
    ImageDraw.Draw(image).rectangle((0, 28, 959, 567), fill=(35, 65, 95))

    bounds = _macos_unity_content_bounds(image)

    assert bounds == WindowBounds(x=0, y=28, width=960, height=540)


def test_macos_decorated_unity_window_supports_retina_non_widescreen_client() -> None:
    image = Image.new("RGB", (1512, 1038), (238, 238, 238))
    ImageDraw.Draw(image).rectangle((0, 56, 1511, 1037), fill=(35, 65, 95))

    bounds = _macos_unity_content_bounds(image)

    assert bounds == WindowBounds(x=0, y=56, width=1512, height=982)


def test_macos_unity_content_detection_rejects_nonstandard_chrome() -> None:
    image = Image.new("RGB", (960, 568), (25, 25, 25))

    assert _macos_unity_content_bounds(image) is None


def _observation(
    sequence: int,
    *,
    paused: bool,
    scene: SoftwareIncUIScene,
    modal: ModalState = ModalState.NONE,
) -> ObservedSoftwareIncUI:
    capture = capture_fixture(
        _image(management=scene is SoftwareIncUIScene.MANAGE_TEAMS), sequence=sequence
    )
    snapshot = _snapshot(sequence * 2, paused=paused)
    target = VisualTarget(
        target_id=(
            "pause_button"
            if scene in {SoftwareIncUIScene.GAMEPLAY_PAUSED, SoftwareIncUIScene.GAMEPLAY_RUNNING}
            else "unused"
        ),
        source_frame_id=capture.metadata.frame_id,
        point=ScreenPoint(x=700, y=260),
        scene=scene,
        projection_id="a" * 64,
        confidence=0.95,
        evidence=("fixture",),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    targets = [target] if scene is not SoftwareIncUIScene.MANAGE_TEAMS else []
    if scene in {SoftwareIncUIScene.GAMEPLAY_PAUSED, SoftwareIncUIScene.GAMEPLAY_RUNNING}:
        targets.append(
            VisualTarget(
                target_id="resume_button",
                source_frame_id=capture.metadata.frame_id,
                point=ScreenPoint(x=727, y=260),
                scene=scene,
                projection_id="a" * 64,
                confidence=0.9,
                evidence=("fixture",),
                expires_at=datetime.now(UTC) + timedelta(seconds=30),
            )
        )
        targets.append(
            VisualTarget(
                target_id="manage_teams_button",
                source_frame_id=capture.metadata.frame_id,
                point=ScreenPoint(x=195, y=798 // 2 + 33),
                scene=scene,
                projection_id="a" * 64,
                confidence=0.9,
                evidence=("fixture",),
                expires_at=datetime.now(UTC) + timedelta(seconds=30),
            )
        )
    observation = SoftwareIncUIObservation(
        semantic_before=snapshot,
        semantic_after=snapshot,
        frame=capture.metadata,
        scene=scene,
        modal_state=modal,
        projection_id="a" * 64,
        targets=tuple(targets),
        synchronization_started_at=datetime.now(UTC),
        synchronization_completed_at=datetime.now(UTC),
        synchronization_duration_seconds=0.1,
        semantic_capture_skew_seconds=0.05,
    )
    return ObservedSoftwareIncUI(observation, capture)


class _Backend:
    def __init__(self) -> None:
        self.gestures: list[InputGesture] = []

    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> InputExecutionResult:
        assert gesture.expected_frame_id == frame.frame_id
        self.gestures.append(gesture)
        return InputExecutionResult(gesture=gesture, sent_at=datetime.now(UTC))


class _Observer:
    def __init__(self, observations: list[ObservedSoftwareIncUI]) -> None:
        self._observations = iter(observations)
        self.backend = _Backend()

    async def observe(self) -> ObservedSoftwareIncUI:
        return next(self._observations)


def test_recognizes_gameplay_target_and_management_panel() -> None:
    gameplay = capture_fixture(_image())
    scene, modal, _, targets = recognize_ui(gameplay, paused=True)
    assert scene is SoftwareIncUIScene.GAMEPLAY_PAUSED
    assert modal is ModalState.NONE
    assert {target.target_id for target in targets} == {
        "manage_teams_button",
        "pause_button",
        "resume_button",
    }
    management = capture_fixture(_image(management=True), sequence=2)
    management_scene, _, _, management_targets = recognize_ui(management, paused=True)
    assert management_scene is SoftwareIncUIScene.MANAGE_TEAMS
    assert "open_hiring" in {target.target_id for target in management_targets}


def test_recognizes_wide_screen_top_edge_time_strip() -> None:
    gameplay = capture_fixture(_image(time_x=545, time_y=5, time_width=40))

    scene, modal, _, targets = recognize_ui(gameplay, paused=True)

    assert scene is SoftwareIncUIScene.GAMEPLAY_PAUSED
    assert modal is ModalState.NONE
    assert {"pause_button", "resume_button"}.issubset({target.target_id for target in targets})


def test_read_only_capture_race_is_retried_once() -> None:
    expected = capture_fixture(_image())

    class Backend:
        attempts = 0

        def capture(self, *, process_id: int) -> CapturedDesktopFrame:
            assert process_id == 77
            self.attempts += 1
            if self.attempts == 1:
                raise StaleDesktopFrameError("window changed during capture")
            return expected

    backend = Backend()

    captured = capture_with_retry(backend, process_id=77)  # type: ignore[arg-type]

    assert captured is expected
    assert backend.attempts == 2


def test_active_viewport_excludes_horizontal_and_vertical_letterboxing() -> None:
    image = Image.new("RGB", (240, 140), "black")
    ImageDraw.Draw(image).rectangle((15, 10, 224, 129), fill=(40, 60, 80))

    assert _active_viewport_bounds(image) == WindowBounds(
        x=15,
        y=10,
        width=210,
        height=120,
    )


def test_semantic_viewport_composes_macos_title_bar_and_letterboxing() -> None:
    image = Image.new("RGB", (480, 300), (238, 238, 238))
    ImageDraw.Draw(image).rectangle((0, 28, 479, 299), fill="black")
    ImageDraw.Draw(image).rectangle((15, 28, 464, 279), fill=(40, 60, 80))
    capture = capture_fixture(image)

    assert _semantic_viewport_bounds(capture, image) == WindowBounds(
        x=15,
        y=28,
        width=450,
        height=252,
    )


def test_product_combo_rows_use_catalog_order_and_observed_endpoint_geometry() -> None:
    state = ObservedEntity(
        entity_type="product_ui_state",
        entity_id="current",
        values={
            "type_items": "Operating System|2D Editor|Audio Tool|Game|Antivirus",
            "category_items": "Computer|Console",
        },
    )

    def anchor(entity_id: str, label: str, y_ratio: float) -> ObservedEntity:
        return ObservedEntity(
            entity_type="ui_target",
            entity_id=entity_id,
            values={
                "callbacks": ".AddTeam",
                "height_ratio": 0.02,
                "interactable": True,
                "kind": "button",
                "label": label,
                "object_name": "ComboButton2(Clone)",
                "path": "Canvas/ComboPanel/ComboButton2(Clone)",
                "width_ratio": 0.1,
                "x_ratio": 0.2,
                "y_ratio": y_ratio,
            },
        )

    product_entities = (state, anchor("first", "Operating System", 0.2))
    last = anchor("last", "Antivirus", 0.28)
    snapshot = _snapshot(1, paused=True)
    surfaces = tuple(
        surface.model_copy(
            update={
                "entities": (
                    product_entities
                    if surface.coverage.surface == "product_ui"
                    else (last,)
                    if surface.coverage.surface == "education_ui"
                    else ()
                )
            }
        )
        for surface in snapshot.surfaces
    )

    entities = _synthetic_product_combo_entities(
        snapshot.model_copy(update={"surfaces": surfaces}), state
    )

    assert [entity.entity_id for entity in entities] == [
        "product_combo_item:operating system",
        "product_combo_item:2d editor",
        "product_combo_item:audio tool",
        "product_combo_item:game",
        "product_combo_item:antivirus",
    ]
    y_ratio_values = [entity.values["y_ratio"] for entity in entities]
    assert all(isinstance(value, (int, float)) for value in y_ratio_values)
    actual_y_ratios = [float(value) for value in y_ratio_values if isinstance(value, (int, float))]
    assert all(
        isclose(actual, expected)
        for actual, expected in zip(actual_y_ratios, [0.2, 0.22, 0.24, 0.26, 0.28], strict=True)
    )


def test_transient_read_only_window_discovery_is_retried_once() -> None:
    expected = capture_fixture(_image())

    class Backend:
        attempts = 0

        def capture(self, *, process_id: int) -> CapturedDesktopFrame:
            assert process_id == 77
            self.attempts += 1
            if self.attempts == 1:
                raise ComputerControlError("window temporarily offscreen during Space activation")
            return expected

    backend = Backend()

    captured = capture_with_retry(backend, process_id=77)  # type: ignore[arg-type]

    assert captured is expected
    assert backend.attempts == 2


def test_exact_semantic_pause_menu_overrides_blurred_gameplay() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    staffing_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "staffing_ui"
    )
    surfaces[staffing_index] = surfaces[staffing_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="staffing_ui_state",
                    entity_id="current",
                    values={"scene": "gameplay"},
                ),
                ObservedEntity(
                    entity_type="ui_target",
                    entity_id="global-button-resume",
                    values={
                        "callbacks": "PauseWindow.DoAction",
                        "height_ratio": 0.0324,
                        "interactable": True,
                        "kind": "button",
                        "label": "Resume",
                        "object_name": "ResumeButton",
                        "path": "Canvas/PauseMenu/Panel/ResumeButton",
                        "width_ratio": 0.1,
                        "x_ratio": 0.5,
                        "y_ratio": 0.3667,
                    },
                ),
            )
        }
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    scene, modal, _, targets = recognize_ui(
        capture_fixture(_image()), snapshot=snapshot, paused=True
    )

    assert scene is SoftwareIncUIScene.PAUSE_MENU
    assert modal is ModalState.NONE
    assert [target.target_id for target in targets] == ["close_pause_menu"]


def test_contract_browser_exposes_exact_window_close_target() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    contract_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "contract_ui"
    )
    surfaces[contract_index] = surfaces[contract_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="contract_ui_state",
                    entity_id="current",
                    values={"scene": "contract_browser"},
                ),
                ObservedEntity(
                    entity_type="ui_target",
                    entity_id="contract-button-close",
                    values={
                        "callbacks": "GUIWindow.CloseClick",
                        "height_ratio": 0.0213,
                        "interactable": True,
                        "kind": "button",
                        "label": "",
                        "object_name": "CloseButton",
                        "path": "Canvas/ContractWindow/TopPanel/CloseButton",
                        "width_ratio": 0.012,
                        "x_ratio": 0.726,
                        "y_ratio": 0.129,
                    },
                ),
                ObservedEntity(
                    entity_type="ui_target",
                    entity_id="work-item-42-button-1",
                    values={
                        "callbacks": "GUIWorkItem.PauseWork",
                        "height_ratio": 0.024,
                        "interactable": True,
                        "kind": "button",
                        "label": "",
                        "object_name": "PauseButton",
                        "path": (
                            "Canvas/MainPanel/Holder/WorkPanel/Panel/DesignContract/PauseButton"
                        ),
                        "width_ratio": 0.014,
                        "x_ratio": 0.876,
                        "y_ratio": 0.134,
                    },
                ),
            )
        }
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    scene, modal, _, targets = recognize_ui(
        capture_fixture(_image()), snapshot=snapshot, paused=True
    )

    assert scene is SoftwareIncUIScene.CONTRACT_BROWSER
    assert modal is ModalState.NONE
    assert "close_contract_browser" in {target.target_id for target in targets}
    assert "work-item-42-toggle-pause" in {target.target_id for target in targets}


def test_completed_peer_review_exposes_exact_finish_target() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    contract_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "contract_ui"
    )
    surfaces[contract_index] = surfaces[contract_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="contract_ui_state",
                    entity_id="current",
                    values={"scene": "gameplay"},
                ),
                ObservedEntity(
                    entity_type="ui_target",
                    entity_id="work-item-91-button-0",
                    values={
                        "callbacks": ".AddTeam",
                        "height_ratio": 0.04,
                        "interactable": True,
                        "kind": "button",
                        "label": "Finish",
                        "object_name": "FinishButton",
                        "path": (
                            "Canvas/MainPanel/Holder/WorkPanel/Panel/Peer review/"
                            "ButtonPanel/FinishButton"
                        ),
                        "width_ratio": 0.16,
                        "x_ratio": 0.9,
                        "y_ratio": 0.3,
                    },
                ),
            )
        }
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    _, modal, _, targets = recognize_ui(capture_fixture(_image()), snapshot=snapshot, paused=True)

    assert modal is ModalState.NONE
    assert "work-item-91-finish-review" in {target.target_id for target in targets}


def test_beta_contract_finish_button_exposes_exact_release_target() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    contract_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "contract_ui"
    )
    surfaces[contract_index] = surfaces[contract_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="contract_ui_state",
                    entity_id="current",
                    values={"scene": "gameplay"},
                ),
                ObservedEntity(
                    entity_type="ui_target",
                    entity_id="work-item-4-button-5",
                    values={
                        "callbacks": ".AddTeam",
                        "height_ratio": 0.04,
                        "interactable": True,
                        "kind": "button",
                        "label": "Finish",
                        "object_name": "FinishButton",
                        "path": (
                            "Canvas/MainPanel/Holder/WorkPanel/Panel/DevelopmentContract/"
                            "ButtonPanel/FinishButton"
                        ),
                        "width_ratio": 0.16,
                        "x_ratio": 0.9,
                        "y_ratio": 0.3,
                    },
                ),
            )
        }
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    _, modal, _, targets = recognize_ui(capture_fixture(_image()), snapshot=snapshot, paused=True)

    assert modal is ModalState.NONE
    assert "work-item-4-release" in {target.target_id for target in targets}


def test_peer_review_result_exposes_exact_promotion_and_close_targets() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    contract_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "contract_ui"
    )

    def target(identity: str, label: str, object_name: str, callbacks: str) -> ObservedEntity:
        return ObservedEntity(
            entity_type="ui_target",
            entity_id=identity,
            values={
                "callbacks": callbacks,
                "height_ratio": 0.04,
                "interactable": True,
                "kind": "button",
                "label": label,
                "object_name": object_name,
                "path": f"Canvas/FinalReviewWindow/{object_name}",
                "width_ratio": 0.16,
                "x_ratio": 0.4,
                "y_ratio": 0.4,
            },
        )

    surfaces[contract_index] = surfaces[contract_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="contract_ui_state",
                    entity_id="current",
                    values={"scene": "contract_review_result"},
                ),
                target(
                    "contract-review-result-button-0",
                    "Promote to beta",
                    "PromoteButton",
                    "FinalReviewWindow.Promote",
                ),
                target(
                    "contract-review-result-button-1",
                    "",
                    "CloseButton",
                    "GUIWindow.CloseClick",
                ),
            )
        }
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    scene, modal, _, targets = recognize_ui(
        capture_fixture(_image(management=True)), snapshot=snapshot, paused=True
    )

    assert scene is SoftwareIncUIScene.CONTRACT_REVIEW_RESULT
    assert modal is ModalState.NONE
    assert {target.target_id for target in targets}.issuperset(
        {"review_result_promote", "close_review_result"}
    )


def test_contract_work_item_card_target_uses_exact_three_anchor_geometry() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    contract_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "contract_ui"
    )
    parent = "Canvas/MainPanel/Holder/WorkPanel/Panel/DesignContract"

    def anchor(
        identity: str,
        object_name: str,
        x_ratio: float,
        y_ratio: float,
        callbacks: str = "",
    ) -> ObservedEntity:
        return ObservedEntity(
            entity_type="ui_target",
            entity_id=identity,
            values={
                "callbacks": callbacks,
                "height_ratio": 0.025,
                "interactable": True,
                "kind": "button",
                "label": "",
                "object_name": object_name,
                "path": f"{parent}/{object_name}",
                "width_ratio": 0.014,
                "x_ratio": x_ratio,
                "y_ratio": y_ratio,
            },
        )

    surfaces[contract_index] = surfaces[contract_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="contract_ui_state",
                    entity_id="current",
                    values={"scene": "gameplay"},
                ),
                anchor(
                    "work-item-42-button-1",
                    "PauseButton",
                    0.876,
                    0.27,
                    "GUIWorkItem.PauseWork",
                ),
                anchor("work-item-42-button-2", "PriorityDown", 0.996, 0.29),
                anchor("work-item-42-button-3", "PriorityUp", 0.996, 0.25),
            )
        }
    )
    work_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "work_items"
    )
    surfaces[work_index] = surfaces[work_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="work_item",
                    entity_id="42",
                    values={"is_contract": True, "name": "Acme"},
                ),
            )
        }
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    scene, modal, _, targets = recognize_ui(
        capture_fixture(_image()), snapshot=snapshot, paused=True
    )

    card = next(target for target in targets if target.target_id == "work-item-42-open")
    assert scene is SoftwareIncUIScene.GAMEPLAY_PAUSED
    assert modal is ModalState.NONE
    assert card.confidence >= 0.8
    assert "Pause, PriorityUp, and PriorityDown" in " ".join(card.evidence)


def test_contract_work_item_card_target_rejects_mixed_parent_anchors() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    contract_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "contract_ui"
    )
    surfaces[contract_index] = surfaces[contract_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="contract_ui_state",
                    entity_id="current",
                    values={"scene": "gameplay"},
                ),
                *tuple(
                    ObservedEntity(
                        entity_type="ui_target",
                        entity_id=f"work-item-42-button-{index}",
                        values={
                            "callbacks": (
                                "GUIWorkItem.PauseWork" if object_name == "PauseButton" else ""
                            ),
                            "height_ratio": 0.025,
                            "interactable": True,
                            "kind": "button",
                            "label": "",
                            "object_name": object_name,
                            "path": f"Canvas/{parent}/{object_name}",
                            "width_ratio": 0.014,
                            "x_ratio": x_ratio,
                            "y_ratio": y_ratio,
                        },
                    )
                    for index, object_name, parent, x_ratio, y_ratio in (
                        (1, "PauseButton", "CardA", 0.876, 0.27),
                        (2, "PriorityDown", "CardA", 0.996, 0.29),
                        (3, "PriorityUp", "CardB", 0.996, 0.25),
                    )
                ),
            )
        }
    )
    work_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "work_items"
    )
    surfaces[work_index] = surfaces[work_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="work_item",
                    entity_id="42",
                    values={"is_contract": True},
                ),
            )
        }
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    _, _, _, targets = recognize_ui(capture_fixture(_image()), snapshot=snapshot, paused=True)

    assert "work-item-42-open" not in {target.target_id for target in targets}


def test_semantic_gameplay_toolbar_target_replaces_visual_coordinate_guess() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    staffing_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "staffing_ui"
    )
    surfaces[staffing_index] = ObservationSurface(
        coverage=FieldCoverage(
            surface="staffing_ui",
            status=CoverageStatus.OBSERVED_COMPLETE,
            fields=("callbacks", "height_ratio", "interactable", "path", "x_ratio", "y_ratio"),
        ),
        entities=(
            ObservedEntity(
                entity_type="staffing_ui_state",
                entity_id="current",
                values={"scene": "gameplay"},
            ),
            ObservedEntity(
                entity_type="ui_target",
                entity_id="global-button-team",
                values={
                    "callbacks": "MainGui.ShowTeamWindow",
                    "height_ratio": 0.06,
                    "interactable": True,
                    "kind": "button",
                    "label": "",
                    "object_name": "TeamButton",
                    "path": "Canvas/HR/TeamButton",
                    "width_ratio": 0.04,
                    "x_ratio": 0.31,
                    "y_ratio": 0.91,
                },
            ),
        ),
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    scene, modal, _, targets = recognize_ui(
        capture_fixture(_image()), snapshot=snapshot, paused=True
    )
    manage_targets = [target for target in targets if target.target_id == "manage_teams_button"]

    assert scene is SoftwareIncUIScene.GAMEPLAY_PAUSED
    assert modal is ModalState.NONE
    assert len(manage_targets) == 1
    assert any("MainGui.ShowTeamWindow" in item for item in manage_targets[0].evidence)


def test_build_mode_and_visible_catalog_items_use_exact_semantic_targets() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    staffing_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "staffing_ui"
    )
    build_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "build_ui"
    )
    surfaces[staffing_index] = surfaces[staffing_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="staffing_ui_state",
                    entity_id="current",
                    values={"scene": "gameplay"},
                ),
                ObservedEntity(
                    entity_type="ui_target",
                    entity_id="global-build",
                    values={
                        "callbacks": "HUD.BuildModeButton",
                        "height_ratio": 0.0685,
                        "interactable": True,
                        "kind": "button",
                        "label": "",
                        "object_name": "BuildButton",
                        "path": "Canvas/MainPanel/Holder/BuildButton",
                        "width_ratio": 0.0354,
                        "x_ratio": 0.06,
                        "y_ratio": 0.76,
                    },
                ),
                ObservedEntity(
                    entity_type="ui_target",
                    entity_id="global-corner-table",
                    values={
                        "callbacks": ".AddTeam",
                        "height_ratio": 0.0593,
                        "interactable": True,
                        "kind": "button",
                        "label": "",
                        "object_name": "BuildButtonCorner Table",
                        "path": (
                            "Canvas/MainPanel/Holder/BuildPanel/SelectionPanel/ContentPanel/"
                            "Panel/BuildButtonCorner Table"
                        ),
                        "width_ratio": 0.0333,
                        "x_ratio": 0.275,
                        "y_ratio": 0.871,
                    },
                ),
            )
        }
    )
    surfaces[build_index] = surfaces[build_index].model_copy(
        update={
            "entities": (
                ObservedEntity(
                    entity_type="build_ui_state",
                    entity_id="current",
                    values={"scene": "build_mode"},
                ),
            )
        }
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    scene, modal, _, targets = recognize_ui(
        capture_fixture(_image()), snapshot=snapshot, paused=True
    )
    target_ids = {target.target_id for target in targets}

    assert scene is SoftwareIncUIScene.BUILD_MODE
    assert modal is ModalState.NONE
    assert "open_build_mode" in target_ids
    assert "build_catalog_item:Corner Table" in target_ids


def test_read_only_camera_projection_resolves_build_preview_and_room_points() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    build_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "build_ui"
    )
    surfaces[build_index] = ObservationSurface(
        coverage=FieldCoverage(
            surface="build_ui",
            status=CoverageStatus.OBSERVED_COMPLETE,
            fields=("kind", "room_id", "scene", "x_ratio", "y_ratio"),
        ),
        entities=(
            ObservedEntity(
                entity_type="build_ui_state",
                entity_id="current",
                values={"scene": "furniture_placement"},
            ),
            ObservedEntity(
                entity_type="world_target",
                entity_id="placement_preview",
                values={
                    "kind": "placement_preview",
                    "room_id": "3",
                    "x_ratio": 0.5,
                    "y_ratio": 0.5,
                },
            ),
            ObservedEntity(
                entity_type="world_target",
                entity_id="room_candidate_3_0",
                values={
                    "kind": "room_candidate",
                    "room_id": "3",
                    "x_ratio": 0.6,
                    "y_ratio": 0.55,
                },
            ),
        ),
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    scene, modal, _, targets = recognize_ui(
        capture_fixture(_image()), snapshot=snapshot, paused=True
    )

    assert scene is SoftwareIncUIScene.FURNITURE_PLACEMENT
    assert modal is ModalState.NONE
    assert {target.target_id for target in targets} >= {
        "placement_preview",
        "room_candidate_3_0",
    }


def test_room_team_action_uses_current_radial_wedge_not_shared_menu_center() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    build_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "build_ui"
    )
    surfaces[build_index] = ObservationSurface(
        coverage=surfaces[build_index].coverage,
        entities=(
            ObservedEntity(
                entity_type="build_ui_state",
                entity_id="current",
                values={"scene": "room_context_menu"},
            ),
            ObservedEntity(
                entity_type="ui_target",
                entity_id="context_ActionChange Room Team",
                values={
                    "callbacks": "",
                    "height_ratio": 0.303813397442853,
                    "interactable": True,
                    "kind": "context_action",
                    "label": "Switch team",
                    "object_name": "ActionChange Room Team",
                    "path": "Canvas/RightClickPanel/ActionChange Room Team",
                    "width_ratio": 0.170895036061605,
                    "x_ratio": 0.5,
                    "y_ratio": 0.5,
                },
            ),
        ),
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    scene, modal, _, targets = recognize_ui(
        capture_fixture(_image()), snapshot=snapshot, paused=True
    )
    target = next(target for target in targets if target.target_id == "change_room_team")

    assert scene is SoftwareIncUIScene.ROOM_CONTEXT_MENU
    assert modal is ModalState.NONE
    assert target.point is not None
    assert target.point.x > 300
    assert target.point.y < 233
    assert any("Switch team wedge" in evidence for evidence in target.evidence)


def test_move_furniture_action_uses_current_radial_wedge_not_shared_menu_center() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    build_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "build_ui"
    )
    surfaces[build_index] = ObservationSurface(
        coverage=surfaces[build_index].coverage,
        entities=(
            ObservedEntity(
                entity_type="build_ui_state",
                entity_id="current",
                values={"scene": "room_context_menu"},
            ),
            ObservedEntity(
                entity_type="ui_target",
                entity_id="context_ActionMove",
                values={
                    "callbacks": "",
                    "height_ratio": 0.356178467362015,
                    "interactable": True,
                    "kind": "context_action",
                    "label": "Move furniture",
                    "object_name": "ActionMove",
                    "path": "Canvas/RightClickPanel/ActionMove",
                    "width_ratio": 0.200350387891134,
                    "x_ratio": 0.5,
                    "y_ratio": 0.5,
                },
            ),
        ),
    )
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    scene, modal, _, targets = recognize_ui(
        capture_fixture(_image()), snapshot=snapshot, paused=True
    )
    target = next(target for target in targets if target.target_id == "label:move furniture")

    assert scene is SoftwareIncUIScene.ROOM_CONTEXT_MENU
    assert modal is ModalState.NONE
    assert target.point is not None
    assert target.point.x > 300
    assert target.point.y < 233
    assert any("Move furniture wedge" in evidence for evidence in target.evidence)


def test_large_uniform_gameplay_area_is_not_a_blocking_modal() -> None:
    room = _image()
    ImageDraw.Draw(room).rectangle((100, 200, 1100, 600), fill=(48, 48, 56))
    scene, modal, _, _ = recognize_ui(capture_fixture(room), paused=True)
    assert scene is SoftwareIncUIScene.GAMEPLAY_PAUSED
    assert modal is ModalState.NONE


def test_large_uniform_panel_with_rectangular_edges_is_blocking() -> None:
    scene, modal, _, targets = recognize_ui(capture_fixture(_image(modal=True)), paused=True)
    assert scene is SoftwareIncUIScene.BLOCKING_MODAL
    assert modal is ModalState.BLOCKING
    assert targets == ()


def test_only_exact_small_software_inc_help_tip_is_nonblocking() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    staffing_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "staffing_ui"
    )
    help_tip = ObservedEntity(
        entity_type="ui_target",
        entity_id="help-tip",
        values={
            "interactable": True,
            "label": (
                "Some lists allow you to select multiple items by holding ctrl, a range of items "
                "by holding shift or all items by pressing ctrl + A"
            ),
            "object_name": "HelpTipPanel",
            "width_ratio": 0.08,
            "height_ratio": 0.04,
        },
    )
    surfaces[staffing_index] = surfaces[staffing_index].model_copy(update={"entities": (help_tip,)})
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})
    assert known_nonblocking_help_tip(snapshot)

    unknown = help_tip.model_copy(
        update={"values": {**help_tip.values, "label": "Unknown tutorial action"}}
    )
    surfaces[staffing_index] = surfaces[staffing_index].model_copy(update={"entities": (unknown,)})
    assert not known_nonblocking_help_tip(snapshot.model_copy(update={"surfaces": tuple(surfaces)}))


def test_active_dialog_window_is_semantically_blocking() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    staffing_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "staffing_ui"
    )
    dialog = ObservedEntity(
        entity_type="ui_target",
        entity_id="not-now",
        values={"path": "Canvas/DialogWindow(Clone)/ButtonPanel/Button 3(Clone)"},
    )
    surfaces[staffing_index] = surfaces[staffing_index].model_copy(update={"entities": (dialog,)})
    assert semantic_blocking_dialog(snapshot.model_copy(update={"surfaces": tuple(surfaces)}))


def test_release_dialog_derives_exact_yes_target_from_middle_control() -> None:
    snapshot = _snapshot(1, paused=True)
    surfaces = list(snapshot.surfaces)
    staffing_index = next(
        index for index, surface in enumerate(surfaces) if surface.coverage.surface == "staffing_ui"
    )
    middle = ObservedEntity(
        entity_type="ui_target",
        entity_id="global-button-390",
        values={
            "callbacks": ".AddTeam",
            "height_ratio": 0.0315682281059063,
            "interactable": True,
            "kind": "button",
            "label": "Don't ask again",
            "object_name": "Button 3(Clone)",
            "path": "Canvas/DialogWindow(Clone)/ButtonPanel/Button 3(Clone)",
            "width_ratio": 0.063932978917682,
            "x_ratio": 0.5,
            "y_ratio": 0.543279022403259,
        },
    )
    surfaces[staffing_index] = surfaces[staffing_index].model_copy(update={"entities": (middle,)})
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    scene, modal, _, targets = recognize_ui(
        capture_fixture(_image(modal=True)), snapshot=snapshot, paused=True
    )

    assert scene is SoftwareIncUIScene.GAMEPLAY_PAUSED
    assert modal is ModalState.BLOCKING
    yes = next(target for target in targets if target.target_id == "confirm_dialog_yes")
    assert yes.point is not None
    assert yes.point.x < 600


def test_pause_uses_one_gesture_and_fresh_verification() -> None:
    observer = _Observer(
        [
            _observation(1, paused=False, scene=SoftwareIncUIScene.GAMEPLAY_RUNNING),
            _observation(2, paused=True, scene=SoftwareIncUIScene.GAMEPLAY_PAUSED),
        ]
    )
    traces: list[object] = []
    result = asyncio.run(
        execute_ui_action(
            SoftwareIncUIAction.PAUSE,
            observer_factory=lambda: observer,  # type: ignore[arg-type]
            trace_writer=traces.append,
        )
    )
    assert result.verified and result.gestures_sent == 1 and result.cycles == 1
    assert len(observer.backend.gestures) == 1
    assert len(traces) == 1


def test_open_manage_teams_is_one_gesture_in_one_cycle() -> None:
    before = _observation(1, paused=True, scene=SoftwareIncUIScene.GAMEPLAY_PAUSED)
    after = _observation(2, paused=True, scene=SoftwareIncUIScene.MANAGE_TEAMS)
    observer = _Observer([before, after])
    result = asyncio.run(
        execute_ui_action(
            SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
            observer_factory=lambda: observer,  # type: ignore[arg-type]
            trace_writer=lambda _record: None,
        )
    )
    assert result.verified and result.gestures_sent == 1 and result.cycles == 1
    assert len(observer.backend.gestures) == 1


def test_open_manage_teams_settles_with_fresh_observation_without_retrying_input() -> None:
    before = _observation(1, paused=True, scene=SoftwareIncUIScene.GAMEPLAY_PAUSED)
    early = _observation(2, paused=True, scene=SoftwareIncUIScene.GAMEPLAY_PAUSED)
    settled = _observation(3, paused=True, scene=SoftwareIncUIScene.MANAGE_TEAMS)
    observer = _Observer([before, early, settled])

    result = asyncio.run(
        execute_ui_action(
            SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
            observer_factory=lambda: observer,  # type: ignore[arg-type]
            trace_writer=lambda _record: None,
        )
    )

    assert result.verified and result.gestures_sent == 1 and result.cycles == 1
    assert len(observer.backend.gestures) == 1


def test_open_manage_teams_already_open_with_modal_sends_nothing() -> None:
    before = _observation(
        1,
        paused=True,
        scene=SoftwareIncUIScene.MANAGE_TEAMS,
        modal=ModalState.BLOCKING,
    )
    observer = _Observer([before])
    result = asyncio.run(
        execute_ui_action(
            SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
            observer_factory=lambda: observer,  # type: ignore[arg-type]
            trace_writer=lambda _record: None,
        )
    )
    assert result.verified and result.gestures_sent == 0
    assert observer.backend.gestures == []


def test_dry_run_resolves_but_sends_no_gesture() -> None:
    before = _observation(1, paused=True, scene=SoftwareIncUIScene.GAMEPLAY_PAUSED)
    observer = _Observer([before])
    result = asyncio.run(
        execute_ui_action(
            SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
            dry_run=True,
            observer_factory=lambda: observer,  # type: ignore[arg-type]
            trace_writer=lambda _record: None,
        )
    )
    assert result.dry_run and result.gestures_sent == 0
    assert observer.backend.gestures == []


def test_modal_and_unknown_requests_send_nothing() -> None:
    observer = _Observer(
        [
            _observation(
                1,
                paused=True,
                scene=SoftwareIncUIScene.BLOCKING_MODAL,
                modal=ModalState.BLOCKING,
            )
        ]
    )
    with pytest.raises(SoftwareIncUIObservationError, match="modal"):
        asyncio.run(
            execute_ui_action(
                SoftwareIncUIAction.PAUSE,
                observer_factory=lambda: observer,  # type: ignore[arg-type]
            )
        )
    assert observer.backend.gestures == []
    with pytest.raises(Exception, match="unsupported"):
        parse_ui_action("hire ten people")


def test_trace_is_owner_only_and_contains_no_pixels(tmp_path: Path) -> None:
    observation = _observation(1, paused=True, scene=SoftwareIncUIScene.GAMEPLAY_PAUSED)
    record = SoftwareIncUITraceRecord(
        action=SoftwareIncUIAction.PAUSE,
        cycle=1,
        observation_frame_id=observation.observation.frame.frame_id,
        bridge_sequence=observation.observation.semantic_after.bridge_sequence,
        scene=observation.observation.scene,
        projection_id=observation.observation.projection_id,
        input_sent=False,
        verified=True,
        reason="already paused",
        recorded_at=datetime.now(UTC),
    )
    path = append_ui_trace(record, path=tmp_path / "private" / "traces.jsonl")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert '"input_sent":false' in path.read_text()
    assert "pixel" not in path.read_text()


def test_synchronization_rejects_identity_and_sequence_drift() -> None:
    capture = capture_fixture(_image())
    before = _snapshot(1, paused=True)
    after = _snapshot(2, paused=True)
    require_ui_continuity(before, after, capture)

    changed = after.model_copy(update={"game_session_id": "different"})
    with pytest.raises(SoftwareIncUIObservationError, match="identity changed"):
        require_ui_continuity(before, changed, capture)
    rollback = after.model_copy(update={"bridge_sequence": 1})
    with pytest.raises(SoftwareIncUIObservationError, match="identity changed"):
        require_ui_continuity(before, rollback, capture)
