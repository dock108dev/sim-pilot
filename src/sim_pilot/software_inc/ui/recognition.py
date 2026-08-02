"""Version-pinned visual scene and target recognition for Software Inc. 1.8.41."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import cast

from PIL import Image

from sim_pilot.computer_control.backend import CapturedDesktopFrame
from sim_pilot.computer_control.models import ScreenPoint, WindowBounds
from sim_pilot.game_bridge.models import GameSnapshot, ObservedEntity

from .models import ModalState, SoftwareIncUIScene, VisualTarget

_TARGET_MAXIMUM_AGE_SECONDS = 10.0
_NONBLOCKING_HELP_TIP_LABELS = frozenset(
    {
        "some lists allow you to select multiple items by holding ctrl, a range of items by "
        "holding shift or all items by pressing ctrl + a",
        "you can right click on a notification to dismiss it",
    }
)


def recognize_ui(
    capture: CapturedDesktopFrame,
    *,
    snapshot: GameSnapshot | None = None,
    paused: bool,
) -> tuple[SoftwareIncUIScene, ModalState, str, tuple[VisualTarget, ...]]:
    """Recognize a supported scene and targets from current-frame pixels."""
    capture = _logical_resolution_capture(capture)
    image = capture.image.convert("RGB")
    gameplay_score, gameplay_evidence = _gameplay_frame_score(image)
    toolbar = _management_toolbar_bounds(image)
    manage_teams_button = _manage_teams_button_peak(image)
    hire_employees_button = _hire_employees_button_peak(image)
    active_time_button = _active_time_button_bounds(image)
    manage_teams_panel = _manage_teams_panel_bounds(image)
    tutorial_modal = _team_tutorial_modal_present(
        image, panel=manage_teams_panel
    ) and not _known_nonblocking_help_tip(snapshot)
    blocking_panel = _blocking_panel_bounds(image, known_panel=manage_teams_panel)
    viewport = _semantic_viewport_bounds(capture, image)
    pause_menu_scene, pause_menu_targets = _pause_menu_ui(capture, snapshot, viewport=viewport)
    staffing_scene, staffing_targets = _staffing_ui(
        capture, snapshot, viewport=viewport, paused=paused
    )
    education_scene, education_targets = _education_ui(capture, snapshot, viewport=viewport)
    office_scene, office_targets = _office_ui(capture, snapshot, viewport=viewport)
    build_scene, build_targets = _build_ui(capture, snapshot, viewport=viewport)
    contract_scene, contract_targets = _contract_ui(capture, snapshot, viewport=viewport)
    product_scene, product_targets = _product_ui(capture, snapshot, viewport=viewport)
    semantic_targets = (
        pause_menu_targets
        if pause_menu_scene is not None
        else (
            *staffing_targets,
            *office_targets,
            *education_targets,
            *build_targets,
            *contract_targets,
            *product_targets,
        )
    )
    projection_id = _projection_id(
        capture,
        toolbar,
        active_time_button,
        manage_teams_panel,
        staffing_targets=semantic_targets,
    )
    semantic_scene = (
        pause_menu_scene
        or product_scene
        or contract_scene
        or education_scene
        or build_scene
        or office_scene
        or staffing_scene
        or (
            SoftwareIncUIScene.GAMEPLAY_PAUSED
            if _semantic_blocking_dialog(snapshot) and paused
            else None
        )
    )
    if semantic_scene is not None:
        scene = semantic_scene
        modal = (
            ModalState.NONE
            if scene is SoftwareIncUIScene.PAUSE_MENU
            else (
                ModalState.BLOCKING
                if _semantic_blocking_dialog(snapshot)
                or (tutorial_modal and scene is SoftwareIncUIScene.MANAGE_TEAMS)
                or (
                    blocking_panel is not None
                    and scene
                    not in {
                        SoftwareIncUIScene.HIRING_CONFIRMATION,
                        SoftwareIncUIScene.BUILD_SEARCH,
                        SoftwareIncUIScene.BUILD_MODE,
                        SoftwareIncUIScene.FURNITURE_PLACEMENT,
                        SoftwareIncUIScene.ROOM_CONTEXT_MENU,
                        SoftwareIncUIScene.ROOM_TEAM_SELECTION,
                        SoftwareIncUIScene.CONTRACT_BROWSER,
                        SoftwareIncUIScene.CONTRACT_TEAM_SELECTION,
                        SoftwareIncUIScene.CONTRACT_REVIEW_SETUP,
                        SoftwareIncUIScene.CONTRACT_REVIEW_RESULT,
                        SoftwareIncUIScene.EDUCATION,
                        SoftwareIncUIScene.PRODUCT_CONFIGURATION,
                        SoftwareIncUIScene.PRODUCT_TEAM_SELECTION,
                    }
                )
                else ModalState.NONE
            )
        )
    elif manage_teams_panel is not None and gameplay_score >= 0.5:
        scene = SoftwareIncUIScene.MANAGE_TEAMS
        modal = ModalState.BLOCKING if tutorial_modal else ModalState.NONE
    elif blocking_panel is not None:
        scene = SoftwareIncUIScene.BLOCKING_MODAL
        modal = ModalState.BLOCKING
    elif gameplay_score >= 0.5:
        scene = (
            SoftwareIncUIScene.GAMEPLAY_PAUSED if paused else SoftwareIncUIScene.GAMEPLAY_RUNNING
        )
        modal = ModalState.NONE
    else:
        scene = SoftwareIncUIScene.UNKNOWN
        modal = ModalState.UNKNOWN
    targets: list[VisualTarget] = []
    expires_at = capture.metadata.captured_at + timedelta(seconds=_TARGET_MAXIMUM_AGE_SECONDS)
    targets.extend(
        target.model_copy(
            update={
                "scene": scene,
                "projection_id": projection_id,
                "expires_at": expires_at,
            }
        )
        for target in semantic_targets
    )
    targets.extend(
        target.model_copy(
            update={
                "scene": scene,
                "projection_id": projection_id,
                "expires_at": expires_at,
            }
        )
        for target in _confirmation_dialog_targets(
            capture,
            snapshot,
            scene,
            viewport=viewport,
        )
    )
    if scene in {SoftwareIncUIScene.GAMEPLAY_PAUSED, SoftwareIncUIScene.GAMEPLAY_RUNNING}:
        if active_time_button is not None:
            targets.extend(
                _time_control_targets(
                    capture,
                    active_time_button,
                    paused=paused,
                    scene=scene,
                    projection_id=projection_id,
                    expires_at=expires_at,
                    gameplay_evidence=gameplay_evidence,
                )
            )
        if (
            toolbar is not None
            and manage_teams_button is not None
            and not any(target.target_id == "manage_teams_button" for target in targets)
        ):
            targets.append(
                _manage_teams_target(
                    capture,
                    toolbar,
                    manage_teams_button,
                    scene,
                    projection_id,
                    expires_at,
                )
            )
    if (
        scene in {SoftwareIncUIScene.MANAGE_TEAMS, SoftwareIncUIScene.CREATE_TEAM_FORM}
        and toolbar is not None
        and hire_employees_button is not None
    ):
        targets.append(
            _management_toolbar_target(
                capture,
                hire_employees_button,
                scene,
                projection_id,
                expires_at,
                target_id="open_hiring",
                control_name="Hire employees",
            )
        )
    return scene, modal, projection_id, tuple(targets)


def _product_ui(
    capture: CapturedDesktopFrame,
    snapshot: GameSnapshot | None,
    *,
    viewport: WindowBounds,
) -> tuple[SoftwareIncUIScene | None, tuple[VisualTarget, ...]]:
    if snapshot is None:
        return None, ()
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == "product_ui"
    ]
    if len(surfaces) != 1:
        return None, ()
    states = [
        entity
        for entity in surfaces[0].entities
        if entity.entity_type == "product_ui_state" and entity.entity_id == "current"
    ]
    if len(states) != 1:
        return None, ()
    semantic_scene = states[0].values.get("scene")
    scene_by_value = {
        "product_configuration": SoftwareIncUIScene.PRODUCT_CONFIGURATION,
        "product_team_selection": SoftwareIncUIScene.PRODUCT_TEAM_SELECTION,
    }
    scene = scene_by_value.get(semantic_scene) if isinstance(semantic_scene, str) else None
    target_scene = scene or SoftwareIncUIScene.GAMEPLAY_PAUSED
    targets = [
        target
        for entity in surfaces[0].entities
        if entity.entity_type == "ui_target"
        if (target := _semantic_ui_target(capture, entity, target_scene, viewport=viewport))
        is not None
    ]
    targets.extend(
        target
        for entity in _synthetic_product_combo_entities(snapshot, states[0])
        if (target := _semantic_ui_target(capture, entity, target_scene, viewport=viewport))
        is not None
    )
    return scene, tuple(targets)


def _synthetic_product_combo_entities(
    snapshot: GameSnapshot, state: ObservedEntity
) -> tuple[ObservedEntity, ...]:
    """Resolve cloned combo rows from ordered game data and observed endpoint geometry."""
    candidate_items: list[tuple[str, ...]] = []
    for field in ("type_items", "category_items"):
        value = state.values.get(field)
        if isinstance(value, str):
            items = tuple(item for item in value.split("|") if item)
            if items:
                candidate_items.append(items)
    anchors: dict[str, tuple[ObservedEntity, float]] = {}
    for surface in snapshot.surfaces:
        for entity in surface.entities:
            if entity.entity_type != "ui_target":
                continue
            values = entity.values
            if values.get("object_name") != "ComboButton2(Clone)":
                continue
            label = values.get("label")
            y_ratio = values.get("y_ratio")
            if not isinstance(label, str) or not label:
                continue
            if isinstance(y_ratio, bool) or not isinstance(y_ratio, (int, float)):
                continue
            anchors[label] = (entity, float(y_ratio))
    anchor_labels = set(anchors)
    matching = [items for items in candidate_items if anchor_labels and anchor_labels <= set(items)]
    if len(matching) != 1:
        return ()
    items = matching[0]
    indexed = sorted(
        (
            items.index(label),
            y_ratio,
            entity,
        )
        for label, (entity, y_ratio) in anchors.items()
        if label in items
    )
    if len(items) == 1:
        first_index, first_y, geometry = indexed[0]
        assert first_index == 0
        y_step = 0.0
    else:
        first_index, first_y, geometry = indexed[0]
        last_index, last_y, _ = indexed[-1]
        if first_index == last_index:
            return ()
        y_step = (last_y - first_y) / (last_index - first_index)
        if y_step <= 0:
            return ()
    base_y = first_y - first_index * y_step
    common = dict(geometry.values)
    return tuple(
        ObservedEntity(
            entity_type="ui_target",
            entity_id=f"product_combo_item:{item.casefold()}",
            values={
                **common,
                "label": item,
                "path": f"Canvas/ComboPanel/ComboButton2(Clone)[{index}]",
                "y_ratio": base_y + index * y_step,
            },
        )
        for index, item in enumerate(items)
    )


def _confirmation_dialog_targets(
    capture: CapturedDesktopFrame,
    snapshot: GameSnapshot | None,
    scene: SoftwareIncUIScene,
    *,
    viewport: WindowBounds,
) -> tuple[VisualTarget, ...]:
    """Resolve the left Yes button from the exact observed three-button dialog.

    Software Inc. 1.8.41 exposes only the middle ``Don't ask again`` control as
    a Unity ``Button`` in this dialog prefab. The adjacent Yes control is a
    custom pointer control. Derive Yes only from that exact active middle path,
    its pinned sibling spacing, and a live non-uniform pixel region; callers
    still bind it to the immediately preceding approved action.
    """
    if snapshot is None:
        return ()
    candidates = [
        entity
        for surface in snapshot.surfaces
        for entity in surface.entities
        if entity.entity_type == "ui_target"
        and entity.values.get("label") == "Don't ask again"
        and entity.values.get("object_name") == "Button 3(Clone)"
        and entity.values.get("path") == "Canvas/DialogWindow(Clone)/ButtonPanel/Button 3(Clone)"
        and entity.values.get("interactable") is True
    ]
    if len(candidates) != 1:
        return ()
    middle_button = candidates[0]
    values = middle_button.values
    x_ratio = values.get("x_ratio")
    width_ratio = values.get("width_ratio")
    if (
        not isinstance(x_ratio, (int, float))
        or isinstance(x_ratio, bool)
        or not isinstance(width_ratio, (int, float))
        or isinstance(width_ratio, bool)
    ):
        return ()
    yes_button = middle_button.model_copy(
        update={
            "entity_id": "confirm_dialog_yes",
            "values": {
                **values,
                "callbacks": "derived from exact three-control DialogWindow layout",
                "label": "Yes",
                "object_name": "Button 1(derived)",
                "path": "Canvas/DialogWindow(Clone)/ButtonPanel/Button 1(derived)",
                "x_ratio": float(x_ratio) - float(width_ratio) * 1.14,
            },
        }
    )
    target = _semantic_ui_target(capture, yes_button, scene, viewport=viewport)
    if target is None:
        return ()
    return (
        target.model_copy(
            update={
                "evidence": (
                    "Yes position derived from the exact active Software Inc. 1.8.41 "
                    "DialogWindow and its observed middle Don't ask again control",
                    *target.evidence,
                )
            }
        ),
    )


def _logical_resolution_capture(capture: CapturedDesktopFrame) -> CapturedDesktopFrame:
    """Analyze HiDPI pixels once at logical resolution while preserving frame identity."""
    scale = capture.metadata.display_scale
    if scale <= 1.1 or capture.image.width * capture.image.height <= 2_000_000:
        return capture
    width = max(1, round(capture.image.width / scale))
    height = max(1, round(capture.image.height / scale))
    image = capture.image.resize(  # pyright: ignore[reportUnknownMemberType]
        (width, height), Image.Resampling.BILINEAR
    )
    metadata = capture.metadata.model_copy(
        update={
            "pixel_width": width,
            "pixel_height": height,
            "display_scale": 1.0,
        }
    )
    return CapturedDesktopFrame(metadata, image)


def _pause_menu_ui(
    capture: CapturedDesktopFrame,
    snapshot: GameSnapshot | None,
    *,
    viewport: WindowBounds,
) -> tuple[SoftwareIncUIScene | None, tuple[VisualTarget, ...]]:
    """Recognize the exact built-in pause menu from semantic UI and live pixels."""
    if snapshot is None:
        return None, ()
    candidates: list[ObservedEntity] = []
    for surface in snapshot.surfaces:
        if surface.coverage.surface != "staffing_ui":
            continue
        for entity in surface.entities:
            if entity.entity_type != "ui_target":
                continue
            values = entity.values
            label = values.get("label")
            object_name = values.get("object_name")
            path = values.get("path")
            callbacks = values.get("callbacks")
            if (
                isinstance(label, str)
                and " ".join(label.casefold().split()) == "resume"
                and object_name == "ResumeButton"
                and isinstance(path, str)
                and path.endswith("/PauseMenu/Panel/ResumeButton")
                and isinstance(callbacks, str)
                and "PauseWindow.DoAction" in callbacks
            ):
                candidates.append(entity)
    if len(candidates) != 1:
        return None, ()
    scene = SoftwareIncUIScene.PAUSE_MENU
    target = _semantic_ui_target(capture, candidates[0], scene, viewport=viewport)
    if target is None or target.target_id != "close_pause_menu":
        return None, ()
    return scene, (target,)


def _contract_ui(
    capture: CapturedDesktopFrame,
    snapshot: GameSnapshot | None,
    *,
    viewport: WindowBounds,
) -> tuple[SoftwareIncUIScene | None, tuple[VisualTarget, ...]]:
    if snapshot is None:
        return None, ()
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == "contract_ui"
    ]
    if len(surfaces) != 1:
        return None, ()
    states = [
        entity
        for entity in surfaces[0].entities
        if entity.entity_type == "contract_ui_state" and entity.entity_id == "current"
    ]
    if len(states) != 1:
        return None, ()
    value = states[0].values.get("scene")
    scenes = {
        "contract_browser": SoftwareIncUIScene.CONTRACT_BROWSER,
        "contract_team_selection": SoftwareIncUIScene.CONTRACT_TEAM_SELECTION,
        "contract_review_setup": SoftwareIncUIScene.CONTRACT_REVIEW_SETUP,
        "contract_review_result": SoftwareIncUIScene.CONTRACT_REVIEW_RESULT,
    }
    scene = scenes.get(value) if isinstance(value, str) else None
    target_scene = scene or SoftwareIncUIScene.GAMEPLAY_PAUSED
    ui_entities = [entity for entity in surfaces[0].entities if entity.entity_type == "ui_target"]
    targets = [
        target
        for entity in ui_entities
        if (target := _semantic_ui_target(capture, entity, target_scene, viewport=viewport))
        is not None
    ]
    targets.extend(
        _work_item_card_targets(
            capture,
            snapshot,
            ui_entities,
            target_scene,
            viewport=viewport,
        )
    )
    return scene, tuple(targets)


def _work_item_card_targets(
    capture: CapturedDesktopFrame,
    snapshot: GameSnapshot,
    ui_entities: list[ObservedEntity],
    scene: SoftwareIncUIScene,
    *,
    viewport: WindowBounds,
) -> tuple[VisualTarget, ...]:
    """Derive exact project-card targets from three observed child controls.

    Software Inc. 1.8.41 implements the work-item card itself as a pointer
    handler rather than a Unity ``Button``. The read-only bridge can therefore
    observe its Pause, PriorityUp, and PriorityDown children but not the card's
    click handler through the generic button collector. Derive a safe point in
    the title portion of that same card only when all three anchors, their
    shared parent, and the exact semantic work item agree.
    """
    work_item_ids = {
        entity.entity_id
        for surface in snapshot.surfaces
        if surface.coverage.surface == "work_items"
        for entity in surface.entities
        if entity.entity_type == "work_item"
    }
    anchors_by_item: dict[str, dict[str, ObservedEntity]] = {}
    for entity in ui_entities:
        identity = entity.entity_id
        if not identity.startswith("work-item-") or "-button-" not in identity:
            continue
        item_id = identity.removeprefix("work-item-").split("-button-", 1)[0]
        if item_id not in work_item_ids:
            continue
        object_name = entity.values.get("object_name")
        if object_name in {"PauseButton", "PriorityUp", "PriorityDown"}:
            anchors_by_item.setdefault(item_id, {})[str(object_name)] = entity

    targets: list[VisualTarget] = []
    for item_id, anchors in anchors_by_item.items():
        if set(anchors) != {"PauseButton", "PriorityUp", "PriorityDown"}:
            continue
        pause = anchors["PauseButton"]
        priority_up = anchors["PriorityUp"]
        priority_down = anchors["PriorityDown"]
        if pause.values.get("callbacks") != "GUIWorkItem.PauseWork":
            continue
        path_values = tuple(anchor.values.get("path") for anchor in anchors.values())
        if any(not isinstance(path, str) or "/" not in path for path in path_values):
            continue
        paths = cast("tuple[str, ...]", path_values)
        parents = {path.rsplit("/", 1)[0] for path in paths}
        if len(parents) != 1:
            continue
        ratios = tuple(
            anchor.values.get(axis)
            for anchor in (pause, priority_up, priority_down)
            for axis in ("x_ratio", "y_ratio")
        )
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in ratios):
            continue
        pause_x, pause_y, up_x, up_y, down_x, down_y = cast(
            "tuple[float, float, float, float, float, float]", ratios
        )
        horizontal_span = min(up_x, down_x) - pause_x
        vertical_span = down_y - up_y
        if not (0.04 <= horizontal_span <= 0.2 and 0.008 <= vertical_span <= 0.08):
            continue
        if abs(up_x - down_x) > 0.01 or not up_y < pause_y < down_y:
            continue
        synthetic = ObservedEntity(
            entity_type="ui_target",
            entity_id=f"work-item-{item_id}-open",
            values={
                "callbacks": "",
                "height_ratio": vertical_span * 0.7,
                "interactable": True,
                "kind": "work_item_card",
                "label": "",
                "object_name": next(iter(parents)).rsplit("/", 1)[-1],
                "path": next(iter(parents)),
                # The card's pointer handler is bound to the document icon in
                # the same left column as Pause, not to the adjacent title.
                "width_ratio": max(0.012, horizontal_span * 0.12),
                "x_ratio": pause_x,
                "y_ratio": up_y - vertical_span * 0.9,
            },
        )
        target = _semantic_ui_target(capture, synthetic, scene, viewport=viewport)
        if target is not None:
            targets.append(
                target.model_copy(
                    update={
                        "evidence": (
                            "exact work-item identity observed semantically",
                            "card document-icon point derived from the current Pause, "
                            "PriorityUp, and "
                            "PriorityDown geometry sharing one Unity parent",
                            *target.evidence,
                        )
                    }
                )
            )
    return tuple(targets)


def _build_ui(
    capture: CapturedDesktopFrame,
    snapshot: GameSnapshot | None,
    *,
    viewport: WindowBounds,
) -> tuple[SoftwareIncUIScene | None, tuple[VisualTarget, ...]]:
    if snapshot is None:
        return None, ()
    surfaces = [surface for surface in snapshot.surfaces if surface.coverage.surface == "build_ui"]
    if len(surfaces) != 1:
        return None, ()
    states = [
        entity
        for entity in surfaces[0].entities
        if entity.entity_type == "build_ui_state" and entity.entity_id == "current"
    ]
    if len(states) != 1:
        return None, ()
    semantic_scene = states[0].values.get("scene")
    scene_by_value = {
        "build_search": SoftwareIncUIScene.BUILD_SEARCH,
        "build_mode": SoftwareIncUIScene.BUILD_MODE,
        "furniture_placement": SoftwareIncUIScene.FURNITURE_PLACEMENT,
        "room_context_menu": SoftwareIncUIScene.ROOM_CONTEXT_MENU,
        "room_team_selection": SoftwareIncUIScene.ROOM_TEAM_SELECTION,
    }
    scene = scene_by_value.get(semantic_scene) if isinstance(semantic_scene, str) else None
    target_scene = scene or SoftwareIncUIScene.GAMEPLAY_PAUSED
    targets: list[VisualTarget] = []
    for entity in surfaces[0].entities:
        target: VisualTarget | None = None
        if entity.entity_type == "ui_target":
            target = _semantic_ui_target(capture, entity, target_scene, viewport=viewport)
        elif entity.entity_type == "world_target":
            target = _semantic_world_target(capture, entity, target_scene, viewport=viewport)
        if target is not None:
            targets.append(target)
    return scene, tuple(targets)


def _office_ui(
    capture: CapturedDesktopFrame,
    snapshot: GameSnapshot | None,
    *,
    viewport: WindowBounds,
) -> tuple[SoftwareIncUIScene | None, tuple[VisualTarget, ...]]:
    if snapshot is None:
        return None, ()
    surfaces = [surface for surface in snapshot.surfaces if surface.coverage.surface == "office_ui"]
    if len(surfaces) != 1:
        return None, ()
    states = [
        entity
        for entity in surfaces[0].entities
        if entity.entity_type == "office_ui_state" and entity.entity_id == "current"
    ]
    if len(states) != 1:
        return None, ()
    semantic_scene = states[0].values.get("scene")
    scene_by_value = {
        "employee_management": SoftwareIncUIScene.EMPLOYEE_MANAGEMENT,
        "role_selection": SoftwareIncUIScene.ROLE_SELECTION,
        "server_management": SoftwareIncUIScene.SERVER_MANAGEMENT,
    }
    scene = scene_by_value.get(semantic_scene) if isinstance(semantic_scene, str) else None
    target_scene = scene or SoftwareIncUIScene.MANAGE_TEAMS
    targets = [
        target
        for entity in surfaces[0].entities
        if entity.entity_type == "ui_target"
        if (target := _semantic_ui_target(capture, entity, target_scene, viewport=viewport))
        is not None
    ]
    return scene, tuple(targets)


def _education_ui(
    capture: CapturedDesktopFrame,
    snapshot: GameSnapshot | None,
    *,
    viewport: WindowBounds,
) -> tuple[SoftwareIncUIScene | None, tuple[VisualTarget, ...]]:
    if snapshot is None:
        return None, ()
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == "education_ui"
    ]
    if len(surfaces) != 1:
        return None, ()
    states = [
        entity
        for entity in surfaces[0].entities
        if entity.entity_type == "education_ui_state" and entity.entity_id == "current"
    ]
    if len(states) != 1:
        return None, ()
    semantic_scene = states[0].values.get("scene")
    scene = SoftwareIncUIScene.EDUCATION if semantic_scene == "education" else None
    target_scene = scene or SoftwareIncUIScene.EMPLOYEE_MANAGEMENT
    targets = [
        target
        for entity in surfaces[0].entities
        if entity.entity_type == "ui_target"
        if (target := _semantic_ui_target(capture, entity, target_scene, viewport=viewport))
        is not None
    ]
    return scene, tuple(targets)


def _staffing_ui(
    capture: CapturedDesktopFrame,
    snapshot: GameSnapshot | None,
    *,
    viewport: WindowBounds,
    paused: bool,
) -> tuple[SoftwareIncUIScene | None, tuple[VisualTarget, ...]]:
    if snapshot is None:
        return None, ()
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == "staffing_ui"
    ]
    if len(surfaces) != 1:
        return None, ()
    states = [
        entity
        for entity in surfaces[0].entities
        if entity.entity_type == "staffing_ui_state" and entity.entity_id == "current"
    ]
    if len(states) != 1:
        return None, ()
    semantic_scene = states[0].values.get("scene")
    scene_by_value = {
        "gameplay": (
            SoftwareIncUIScene.GAMEPLAY_PAUSED if paused else SoftwareIncUIScene.GAMEPLAY_RUNNING
        ),
        "manage_teams": SoftwareIncUIScene.MANAGE_TEAMS,
        "create_team_form": SoftwareIncUIScene.CREATE_TEAM_FORM,
        "hiring_setup": SoftwareIncUIScene.HIRING_SETUP,
        "applicant_list": SoftwareIncUIScene.APPLICANT_LIST,
        "hiring_confirmation": SoftwareIncUIScene.HIRING_CONFIRMATION,
    }
    scene = scene_by_value.get(semantic_scene) if isinstance(semantic_scene, str) else None
    if scene is None:
        return None, ()
    if scene is SoftwareIncUIScene.CREATE_TEAM_FORM:
        focused = states[0].values.get("team_name_focused")
        value = states[0].values.get("team_name_value")
        if focused is False and value == "":
            scene = SoftwareIncUIScene.MANAGE_TEAMS
    targets = [
        target
        for entity in surfaces[0].entities
        if entity.entity_type == "ui_target"
        if (target := _semantic_ui_target(capture, entity, scene, viewport=viewport)) is not None
    ]
    return scene, tuple(targets)


def _known_nonblocking_help_tip(snapshot: GameSnapshot | None) -> bool:
    """Recognize only small, exact Software Inc. informational HelpTipPanel text."""
    if snapshot is None:
        return False
    for surface in snapshot.surfaces:
        if surface.coverage.surface != "staffing_ui":
            continue
        for entity in surface.entities:
            if entity.entity_type != "ui_target":
                continue
            values = entity.values
            label = values.get("label")
            object_name = values.get("object_name")
            width = values.get("width_ratio")
            height = values.get("height_ratio")
            if (
                isinstance(label, str)
                and " ".join(label.casefold().split()) in _NONBLOCKING_HELP_TIP_LABELS
                and object_name == "HelpTipPanel"
                and values.get("interactable") is True
                and isinstance(width, (int, float))
                and not isinstance(width, bool)
                and isinstance(height, (int, float))
                and not isinstance(height, bool)
                and 0 < width <= 0.2
                and 0 < height <= 0.1
            ):
                return True
    return False


def _semantic_blocking_dialog(snapshot: GameSnapshot | None) -> bool:
    """Fail closed when the active Unity UI tree contains a dialog window."""
    if snapshot is None:
        return False
    return any(
        entity.entity_type == "ui_target"
        and isinstance(entity.values.get("path"), str)
        and "/DialogWindow(" in cast("str", entity.values["path"])
        for surface in snapshot.surfaces
        for entity in surface.entities
    )


def _semantic_world_target(
    capture: CapturedDesktopFrame,
    entity: ObservedEntity,
    scene: SoftwareIncUIScene,
    *,
    viewport: WindowBounds,
) -> VisualTarget | None:
    values = entity.values
    x_ratio = values.get("x_ratio")
    y_ratio = values.get("y_ratio")
    if (
        not isinstance(x_ratio, (int, float))
        or isinstance(x_ratio, bool)
        or not isinstance(y_ratio, (int, float))
        or isinstance(y_ratio, bool)
        or not 0 <= x_ratio <= 1
        or not 0 <= y_ratio <= 1
    ):
        return None
    image = capture.image.convert("RGB")
    pixel_x = viewport.x + round(x_ratio * viewport.width)
    pixel_y = viewport.y + round(y_ratio * viewport.height)
    if not 0 <= pixel_x < image.width or not 0 <= pixel_y < image.height:
        return None
    radius = max(3, round(min(viewport.width, viewport.height) * 0.006))
    confidence, visual_evidence = _target_pixel_confidence(
        image,
        max(0, pixel_x - radius),
        max(0, pixel_y - radius),
        min(image.width, pixel_x + radius),
        min(image.height, pixel_y + radius),
    )
    if confidence < 0.8:
        return None
    scale = capture.metadata.display_scale
    logical_x = capture.metadata.window_bounds.x + round(pixel_x / scale)
    logical_y = capture.metadata.window_bounds.y + round(pixel_y / scale)
    logical_radius = max(2, round(radius / scale))
    kind = values.get("kind")
    room_id = values.get("room_id")
    return VisualTarget(
        target_id=entity.entity_id,
        source_frame_id=capture.metadata.frame_id,
        point=ScreenPoint(x=logical_x, y=logical_y),
        region=WindowBounds(
            x=logical_x - logical_radius,
            y=logical_y - logical_radius,
            width=logical_radius * 2,
            height=logical_radius * 2,
        ),
        scene=scene,
        projection_id="0" * 64,
        confidence=confidence,
        evidence=(
            "world point projected by the read-only Software Inc. camera API",
            visual_evidence,
            f"kind={kind!r}; room_id={room_id!r}",
        ),
        expires_at=datetime.now(UTC) + timedelta(seconds=_TARGET_MAXIMUM_AGE_SECONDS),
    )


def _semantic_ui_target(
    capture: CapturedDesktopFrame,
    entity: ObservedEntity,
    scene: SoftwareIncUIScene,
    *,
    viewport: WindowBounds,
) -> VisualTarget | None:
    values = entity.values
    ratios = tuple(values.get(key) for key in ("x_ratio", "y_ratio", "width_ratio", "height_ratio"))
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in ratios):
        return None
    x_ratio, y_ratio, width_ratio, height_ratio = cast("tuple[float, float, float, float]", ratios)
    if not (
        0 <= x_ratio <= 1 and 0 <= y_ratio <= 1 and 0 < width_ratio <= 1 and 0 < height_ratio <= 1
    ):
        return None
    interactable = values.get("interactable")
    if interactable is not True:
        return None
    image = capture.image.convert("RGB")
    pixel_x = viewport.x + round(x_ratio * viewport.width)
    pixel_y = viewport.y + round(y_ratio * viewport.height)
    half_width = max(2, round(width_ratio * viewport.width / 2))
    half_height = max(2, round(height_ratio * viewport.height / 2))
    object_value = values.get("object_name")
    path_value = values.get("path")
    radial_change_team = (
        scene is SoftwareIncUIScene.ROOM_CONTEXT_MENU
        and object_value == "ActionChange Room Team"
        and path_value == "Canvas/RightClickPanel/ActionChange Room Team"
    )
    radial_move_furniture = (
        scene is SoftwareIncUIScene.ROOM_CONTEXT_MENU
        and object_value == "ActionMove"
        and path_value == "Canvas/RightClickPanel/ActionMove"
    )
    if radial_change_team:
        menu_width = width_ratio * viewport.width
        menu_height = height_ratio * viewport.height
        pixel_x += round(menu_width * 0.195)
        pixel_y -= round(menu_height * 0.24)
        half_width = max(6, round(menu_width * 0.065))
        half_height = max(6, round(menu_height * 0.065))
    elif radial_move_furniture:
        # Context-action RectTransforms cover the whole radial menu. Resolve
        # the 1.8.41 Move furniture wedge from this exact menu's observed center
        # and diameter instead of clicking the shared center.
        menu_width = width_ratio * viewport.width
        menu_height = height_ratio * viewport.height
        pixel_x += round(menu_width * 0.25)
        pixel_y -= round(menu_height * 0.05)
        half_width = max(6, round(menu_width * 0.06))
        half_height = max(6, round(menu_height * 0.06))
    left = max(0, pixel_x - half_width)
    top = max(0, pixel_y - half_height)
    right = min(image.width, pixel_x + half_width)
    bottom = min(image.height, pixel_y + half_height)
    confidence, visual_evidence = _target_pixel_confidence(image, left, top, right, bottom)
    if confidence < 0.8:
        return None
    scale = capture.metadata.display_scale
    logical_x = capture.metadata.window_bounds.x + round(pixel_x / scale)
    logical_y = capture.metadata.window_bounds.y + round(pixel_y / scale)
    label = values.get("label")
    object_name = values.get("object_name")
    path = values.get("path")
    kind = values.get("kind")
    callbacks = values.get("callbacks")
    label_text = label if isinstance(label, str) else ""
    object_text = object_name if isinstance(object_name, str) else ""
    path_text = path if isinstance(path, str) else ""
    kind_text = kind if isinstance(kind, str) else "control"
    callbacks_text = callbacks if isinstance(callbacks, str) else ""
    target_id = _semantic_target_id(
        entity.entity_id,
        scene=scene,
        label=label_text,
        object_name=object_text,
        path=path_text,
        callbacks=callbacks_text,
    )
    logical_half_width = max(2, round(half_width / scale))
    logical_half_height = max(2, round(half_height / scale))
    return VisualTarget(
        target_id=target_id,
        source_frame_id=capture.metadata.frame_id,
        point=ScreenPoint(x=logical_x, y=logical_y),
        region=WindowBounds(
            x=logical_x - logical_half_width,
            y=logical_y - logical_half_height,
            width=logical_half_width * 2,
            height=logical_half_height * 2,
        ),
        scene=scene,
        projection_id="0" * 64,
        confidence=confidence,
        evidence=(
            "target geometry observed from the active read-only Unity UI tree",
            *(
                (
                    "Software Inc. 1.8.41 Switch team wedge derived from the current radial "
                    "menu center and size",
                )
                if radial_change_team
                else ()
            ),
            *(
                (
                    "Software Inc. 1.8.41 Move furniture wedge derived from the current "
                    "radial menu center and size",
                )
                if radial_move_furniture
                else ()
            ),
            visual_evidence,
            f"kind={kind_text}; label={label_text!r}; object={object_text!r}",
            f"read-only persistent callbacks={callbacks_text!r}",
        ),
        expires_at=datetime.now(UTC) + timedelta(seconds=_TARGET_MAXIMUM_AGE_SECONDS),
    )


def _active_viewport_bounds(image: Image.Image) -> WindowBounds:
    """Resolve the rendered game viewport inside any black capture letterboxing."""
    width, height = image.size
    x_step = max(1, width // 960)
    sampled_x = tuple(range(0, width, x_step))
    minimum_active = max(8, round(len(sampled_x) * 0.05))
    active_rows: list[int] = []
    for y in range(height):
        visible = sum(
            max(cast("tuple[int, int, int]", image.getpixel((x, y)))) > 20 for x in sampled_x
        )
        if visible >= minimum_active:
            active_rows.append(y)
    groups: list[list[int]] = []
    for row in active_rows:
        if not groups or row != groups[-1][-1] + 1:
            groups.append([row])
        else:
            groups[-1].append(row)
    if not groups:
        return WindowBounds(x=0, y=0, width=width, height=height)
    viewport_rows = max(groups, key=len)
    if len(viewport_rows) < height * 0.4:
        return WindowBounds(x=0, y=0, width=width, height=height)
    y_step = max(1, len(viewport_rows) // 540)
    sampled_y = tuple(viewport_rows[::y_step])
    minimum_active_y = max(8, round(len(sampled_y) * 0.05))
    active_columns: list[int] = []
    for x in range(width):
        visible = sum(
            max(cast("tuple[int, int, int]", image.getpixel((x, y)))) > 20 for y in sampled_y
        )
        if visible >= minimum_active_y:
            active_columns.append(x)
    column_groups: list[list[int]] = []
    for column in active_columns:
        if not column_groups or column != column_groups[-1][-1] + 1:
            column_groups.append([column])
        else:
            column_groups[-1].append(column)
    viewport_columns = max(column_groups, key=len) if column_groups else list(range(width))
    if len(viewport_columns) < width * 0.4:
        viewport_columns = list(range(width))
    return WindowBounds(
        x=viewport_columns[0],
        y=viewport_rows[0],
        width=viewport_columns[-1] - viewport_columns[0] + 1,
        height=viewport_rows[-1] - viewport_rows[0] + 1,
    )


def _semantic_viewport_bounds(capture: CapturedDesktopFrame, image: Image.Image) -> WindowBounds:
    """Project Unity's full canvas into a possibly clipped desktop capture."""
    metadata = capture.metadata
    content = metadata.window_content_bounds
    if content is not None and content != metadata.window_bounds:
        scale = metadata.display_scale
        client = WindowBounds(
            x=round((content.x - metadata.window_bounds.x) * scale),
            y=round((content.y - metadata.window_bounds.y) * scale),
            width=round(content.width * scale),
            height=round(content.height * scale),
        )
    else:
        macos_content = _macos_unity_content_bounds(image)
        client = macos_content or WindowBounds(x=0, y=0, width=image.width, height=image.height)
    client_image = image.crop(
        (client.x, client.y, client.x + client.width, client.y + client.height)
    )
    active = _active_viewport_bounds(client_image)
    return WindowBounds(
        x=client.x + active.x,
        y=client.y + active.y,
        width=active.width,
        height=active.height,
    )


def _macos_unity_content_bounds(image: Image.Image) -> WindowBounds | None:
    """Exclude a narrow, bright macOS title bar from a Unity client capture."""
    width, height = image.size
    if width < 200 or height < 100:
        return None
    rgb = image.convert("RGB")
    sample_x = tuple(range(width // 8, width * 7 // 8, max(1, width // 48)))

    def row_luminance(y: int) -> list[float]:
        return [
            red * 0.2126 + green * 0.7152 + blue * 0.0722
            for x in sample_x
            for red, green, blue in [cast("tuple[int, int, int]", rgb.getpixel((x, y)))]
        ]

    baseline = row_luminance(min(8, height - 1))
    if not baseline:
        return None
    chrome_median = sorted(baseline)[len(baseline) // 2]
    matching_chrome = sum(abs(value - chrome_median) <= 24 for value in baseline)
    if chrome_median < 150 or matching_chrome / len(baseline) < 0.75:
        return None
    maximum_title_height = min(96, round(height * 0.15))
    title_height: int | None = None
    for y in range(18, maximum_title_height - 2):
        following_rows = (row_luminance(y + offset) for offset in range(3))
        if all(
            values
            and (
                sorted(values)[len(values) // 2] < chrome_median - 35
                or sum(abs(value - chrome_median) <= 24 for value in values) / len(values) < 0.45
            )
            for values in following_rows
        ):
            title_height = y
            break
    if title_height is None:
        return None
    client_height = height - title_height
    if client_height <= height * 0.75:
        return None
    return WindowBounds(x=0, y=title_height, width=width, height=client_height)


def _semantic_target_id(
    fallback: str,
    *,
    scene: SoftwareIncUIScene,
    label: str,
    object_name: str,
    path: str,
    callbacks: str = "",
) -> str:
    if fallback in {
        "team_name_input",
        "role_combo",
        "wage_combo",
        "team_compatibility",
        "applicant_list",
        "arrival_time_input",
        "departure_time_input",
        "server_name_input",
        "server_list",
        "any_role_toggle",
        "build_search_input",
        "room_team_search",
        "room_team_pass_through",
        "open_contracts",
        "confirm_dialog_yes",
        "education_employee_list",
        "education_role_combo",
        "education_specialization_combo",
    } or fallback.startswith(
        (
            "applicant_row_",
            "team_row_",
            "employee_row_",
            "primary_role_",
            "secondary_role_",
            "build_search_result_",
            "room_team_",
            "contract_row_",
            "contract_result_row_",
            "contract_team_",
            "education_employee_row_",
            "product_feature_",
            "product_os_",
            "product_team_",
            "product_combo_item:",
        )
    ):
        return fallback
    material = " ".join((label, object_name, path, callbacks)).casefold()
    normalized_label = " ".join(label.casefold().split())
    if (
        object_name == "BuildButton"
        and path == "Canvas/MainPanel/Holder/BuildButton"
        and callbacks == "HUD.BuildModeButton"
    ):
        return "open_build_mode"
    if (
        scene
        in {
            SoftwareIncUIScene.GAMEPLAY_PAUSED,
            SoftwareIncUIScene.GAMEPLAY_RUNNING,
        }
        and "hud.employeesbutton" in material
    ):
        return "open_employees"
    if scene is SoftwareIncUIScene.EMPLOYEE_MANAGEMENT and (
        "employeewindow.educate" in material or normalized_label == "educate"
    ):
        return "open_education"
    if scene is SoftwareIncUIScene.EDUCATION and (
        "educationwindow.sendem" in material
        or normalized_label in {"educate", "start education", "send"}
    ):
        return "commit_education"
    if (
        object_name.startswith("BuildButton")
        and "/BuildPanel/SelectionPanel/ContentPanel/Panel/BuildButton" in path
    ):
        prefab_name = object_name.removeprefix("BuildButton")
        if prefab_name:
            return f"build_catalog_item:{prefab_name}"
    if (
        scene is SoftwareIncUIScene.PAUSE_MENU
        and normalized_label == "resume"
        and "resumebutton" in material
        and "pausewindow.doaction" in material
    ):
        return "close_pause_menu"
    if any(value in material for value in ("begin looking", "start looking", "look for hire")):
        return "begin_applicant_search"
    if scene in {
        SoftwareIncUIScene.GAMEPLAY_PAUSED,
        SoftwareIncUIScene.GAMEPLAY_RUNNING,
    } and any(
        value in material
        for value in (
            "teamwindow",
            "showteams",
            "manage teams",
            "manageteams",
            "open team",
            "hud.teamsbutton",
            "teambutton",
        )
    ):
        return "manage_teams_button"
    if scene is SoftwareIncUIScene.CREATE_TEAM_FORM and (
        any(value in material for value in ("create team", "add team", "confirm", "okay", "/add"))
        or (normalized_label == "add" and "teamwindow" in material)
    ):
        return "commit_create_team"
    if scene is SoftwareIncUIScene.MANAGE_TEAMS and any(
        value in material for value in ("add team", "new team", "create team", "/add")
    ):
        return "open_create_team"
    if scene is SoftwareIncUIScene.MANAGE_TEAMS and any(
        value in material for value in ("openhr", "human resources", "hire", "employee")
    ):
        return "open_hiring"
    if scene is SoftwareIncUIScene.APPLICANT_LIST and any(
        value in material for value in ("hire", "employ", "confirm")
    ):
        return "commit_hire"
    if scene is SoftwareIncUIScene.APPLICANT_LIST and any(
        value in material for value in ("pickteam", "select team", "change team", "team:")
    ):
        return "choose_team"
    if scene is SoftwareIncUIScene.MANAGE_TEAMS and any(
        value in material for value in ("applytimes", "apply times", "working hours")
    ):
        return "apply_working_hours"
    if scene is SoftwareIncUIScene.MANAGE_TEAMS and any(
        value in material for value in ("showemployees", "show employees", "employees")
    ):
        return "show_team_employees"
    if scene is SoftwareIncUIScene.EMPLOYEE_MANAGEMENT and any(
        value in material for value in ("changeroles", "change roles", "roles")
    ):
        return "open_role_selection"
    if scene is SoftwareIncUIScene.ROLE_SELECTION and any(
        value in material for value in ("apply", "okay", "confirm")
    ):
        return "apply_roles"
    if scene is SoftwareIncUIScene.ROOM_CONTEXT_MENU and any(
        value in material for value in ("change room team", "changeroomteam")
    ):
        return "change_room_team"
    if scene is SoftwareIncUIScene.ROOM_TEAM_SELECTION and any(
        value in material for value in ("okay", "confirm", "accept", "toggleok", "okbutton")
    ):
        return "apply_room_teams"
    if (
        scene is SoftwareIncUIScene.ROOM_TEAM_SELECTION
        and "guiwindow.closeclick" in material
        and "/teamselectwindow/toppanel/closebutton" in material
    ):
        return "close_room_team_selection"
    if scene is SoftwareIncUIScene.CONTRACT_BROWSER:
        if (
            "guiwindow.closeclick" in material
            and "/contractwindow/toppanel/closebutton" in material
        ):
            return "close_contract_browser"
        if any(
            value in material for value in ("acceptjobs", "accept jobs")
        ) or normalized_label in {
            "accept",
            "accept contract",
        }:
            return "commit_contract"
        if (
            any(value in material for value in ("pickteams", "design team"))
            and "dev" not in material
        ):
            return "pick_contract_design_team"
        if any(value in material for value in ("pickteams", "development team", "dev team")):
            return "pick_contract_development_team"
    if scene is SoftwareIncUIScene.CONTRACT_TEAM_SELECTION and any(
        value in material for value in ("okay", "confirm", "accept", "toggleok", "okbutton")
    ):
        return "apply_contract_teams"
    if scene is SoftwareIncUIScene.CONTRACT_REVIEW_SETUP and (
        any(value in material for value in ("finish", "start review", "begin review"))
        or normalized_label in {"start", "review"}
    ):
        return "commit_contract_review"
    if scene is SoftwareIncUIScene.CONTRACT_REVIEW_RESULT:
        if normalized_label == "promote to beta" or (
            normalized_label == "promote" and "beta" in material
        ):
            return "review_result_promote"
        if normalized_label == "iterate":
            return "review_result_iterate"
        if "guiwindow.closeclick" in material and object_name == "CloseButton":
            return "close_review_result"
    if (
        fallback == "open_product_design"
        and scene
        in {
            SoftwareIncUIScene.GAMEPLAY_PAUSED,
            SoftwareIncUIScene.GAMEPLAY_RUNNING,
        }
        and ("hud.developbutton" in material or object_name == "DesignDocumentButton")
    ):
        return "open_product_design"
    if scene is SoftwareIncUIScene.PRODUCT_CONFIGURATION:
        if (
            object_name == "CloseButton"
            and "guiwindow.closeclick" in material
            and "/designdocumentwindow/toppanel/closebutton" in path.casefold()
        ):
            return "close_product_configuration"
        if object_name == "NextPage" or normalized_label in {"next", "continue"}:
            return "product_next_page"
        if object_name == "PrevPage" or normalized_label in {"previous", "back"}:
            return "product_previous_page"
        if any(value in material for value in ("changeddevteam", "changedevteam")):
            team_material = f"{normalized_label} {object_name.casefold()} {path.casefold()}"
            if any(value in team_material for value in ("design team", "designteam")):
                return "choose_product_design_team"
            if any(value in team_material for value in ("development team", "dev team", "devteam")):
                return "choose_product_development_team"
            return fallback
        if any(
            value in material
            for value in ("generatedesign", "developclick", "actuallygeneratedesign")
        ) or normalized_label in {"design", "start design", "develop"}:
            return "commit_product_design"
    if scene is SoftwareIncUIScene.PRODUCT_TEAM_SELECTION and any(
        value in material for value in ("okay", "confirm", "accept", "toggleok", "okbutton")
    ):
        return "apply_product_teams"
    if fallback.startswith("work-item-"):
        if fallback.endswith("-open"):
            return fallback
        base = fallback.split("-button-")[0]
        if "guiworkitem.toggleopen" in material or object_name in {
            "ExpandIcon",
            "Expander",
        }:
            return base + "-open"
        if object_name == "PauseButton" and "guiworkitem.pausework" in material:
            return fallback.split("-button-")[0] + "-toggle-pause"
        if (
            object_name == "FinishButton"
            and normalized_label == "finish"
            and "/peer review/" in path.casefold()
            and ".addteam" in callbacks.casefold()
        ):
            return base + "-finish-review"
        if (
            object_name == "FinishButton"
            and normalized_label == "finish"
            and "/developmentcontract/" in path.casefold()
            and ".addteam" in callbacks.casefold()
        ):
            return base + "-release"
        if object_name == "ReviewButton" or normalized_label == "review":
            return base + "-review"
        if object_name == "ReleaseButton" or normalized_label in {
            "release",
            "finish contract",
        }:
            return fallback.split("-button-")[0] + "-release"
        if object_name == "PromoteButton" or normalized_label in {
            "promote",
            "develop",
            "alpha",
            "beta",
        }:
            return base + "-promote"
    if normalized_label:
        return f"label:{normalized_label}"
    return fallback


def _target_pixel_confidence(
    image: Image.Image,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> tuple[float, str]:
    if right - left < 4 or bottom - top < 4:
        return 0.0, "target region is too small"
    step = max(1, min(right - left, bottom - top) // 12)
    samples = [
        cast("tuple[int, int, int]", image.getpixel((x, y)))
        for y in range(top, bottom, step)
        for x in range(left, right, step)
    ]
    luminance = [red * 0.2126 + green * 0.7152 + blue * 0.0722 for red, green, blue in samples]
    spread = max(luminance) - min(luminance)
    color_bins = len({(red // 24, green // 24, blue // 24) for red, green, blue in samples})
    confidence = min(0.98, 0.8 + min(spread / 255, 0.12) + min(color_bins / 200, 0.06))
    return confidence, f"current screenshot target region spread={spread:.1f}; bins={color_bins}"


def _active_time_button_bounds(image: Image.Image) -> WindowBounds | None:
    """Resolve the green active speed button in the top-center time-control strip."""
    width, height = image.size
    # Software Inc. moves the time strip flush to the top at wide 16:9 resolutions.
    # Keep the horizontal search centered so green notification-collapse controls at
    # the left cannot masquerade as the active speed button.
    x_start, x_end = round(width * 0.35), round(width * 0.65)
    y_start, y_end = 0, round(height * 0.25)
    step = max(2, width // 1512)
    rows: list[tuple[int, tuple[int, ...]]] = []
    for y in range(y_start, y_end, step):
        green_x: list[int] = []
        for x in range(x_start, x_end, step):
            red, green, blue = cast("tuple[int, int, int]", image.getpixel((x, y)))
            if green > 90 and green > red * 1.25 and green > blue * 1.15:
                green_x.append(x)
        if (
            5 <= len(green_x) <= 150
            and max(green_x, default=0) - min(green_x, default=0) <= width * 0.04
        ):
            rows.append((y, tuple(green_x)))
    if not rows:
        return None
    groups: list[list[tuple[int, tuple[int, ...]]]] = []
    for row in rows:
        if not groups or row[0] - groups[-1][-1][0] > step * 2:
            groups.append([row])
        else:
            groups[-1].append(row)
    groups = [group for group in groups if len(group) * step >= height * 0.015]
    if not groups:
        return None
    candidates: list[WindowBounds] = []
    for group in groups:
        xs = [x for _, row_x in group for x in row_x]
        candidate = WindowBounds(
            x=min(xs),
            y=group[0][0],
            width=max(xs) - min(xs) + step,
            height=group[-1][0] - group[0][0] + step,
        )
        center_x = candidate.x + candidate.width / 2
        if (
            width * 0.012 <= candidate.width <= width * 0.06
            and height * 0.012 <= candidate.height <= height * 0.09
            and width * 0.4 <= center_x <= width * 0.55
        ):
            candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda item: item.y)


def _time_control_targets(
    capture: CapturedDesktopFrame,
    active: WindowBounds,
    *,
    paused: bool,
    scene: SoftwareIncUIScene,
    projection_id: str,
    expires_at: datetime,
    gameplay_evidence: tuple[str, ...],
) -> tuple[VisualTarget, VisualTarget]:
    active_x = active.x + active.width // 2
    active_y = active.y + active.height // 2
    pause_x = active_x if paused else active_x - active.width
    resume_x = active_x + active.width if paused else active_x
    scale = capture.metadata.display_scale

    def target(target_id: str, pixel_x: int, effect: str) -> VisualTarget:
        logical_x = capture.metadata.window_bounds.x + round(pixel_x / scale)
        logical_y = capture.metadata.window_bounds.y + round(active_y / scale)
        return VisualTarget(
            target_id=target_id,
            source_frame_id=capture.metadata.frame_id,
            point=ScreenPoint(x=logical_x, y=logical_y),
            scene=scene,
            projection_id=projection_id,
            confidence=0.91,
            evidence=(
                *gameplay_evidence,
                "green active time-control button visually resolved",
                "equal-width adjacent time-control button derived from current strip",
                effect,
            ),
            expires_at=expires_at,
        )

    return (
        target("pause_button", pause_x, "pause control"),
        target("resume_button", resume_x, "normal-speed control"),
    )


def _gameplay_frame_score(image: Image.Image) -> tuple[float, tuple[str, ...]]:
    width, height = image.size
    step = max(2, width // 756)
    green_border = 0
    border_samples = 0
    non_black = 0
    content_samples = 0
    for y in range(0, height, step):
        for x in (
            *range(0, min(width, step * 3), step),
            *range(max(0, width - step * 3), width, step),
        ):
            red, green, blue = cast("tuple[int, int, int]", image.getpixel((x, y)))
            border_samples += 1
            if green > 90 and green > red * 1.25 and green > blue * 1.15:
                green_border += 1
    for y in range(round(height * 0.18), round(height * 0.86), step * 3):
        for x in range(round(width * 0.05), round(width * 0.95), step * 3):
            red, green, blue = cast("tuple[int, int, int]", image.getpixel((x, y)))
            content_samples += 1
            if max(red, green, blue) > 28:
                non_black += 1
    green_ratio = green_border / max(1, border_samples)
    content_ratio = non_black / max(1, content_samples)
    score = min(1.0, green_ratio * 7.0) * 0.55 + min(1.0, content_ratio * 1.8) * 0.45
    evidence = (
        f"green game-frame border ratio={green_ratio:.3f}",
        f"visible gameplay-content ratio={content_ratio:.3f}",
    )
    return score, evidence


def _management_toolbar_bounds(image: Image.Image) -> WindowBounds | None:
    """Find the anchored bottom-left management toolbar within a broad relative search zone."""
    width, height = image.size
    x_start, x_end = round(width * 0.04), round(width * 0.25)
    y_start, y_end = round(height * 0.73), round(height * 0.86)
    step = max(2, width // 1512)
    row_scores: list[tuple[int, int]] = []
    for y in range(y_start, y_end, step):
        neutral = 0
        for x in range(x_start, x_end, step):
            red, green, blue = cast("tuple[int, int, int]", image.getpixel((x, y)))
            if 80 <= red <= 245 and max(red, green, blue) - min(red, green, blue) < 32:
                neutral += 1
        row_scores.append((neutral, y))
    if not row_scores:
        return None
    threshold = max(score for score, _ in row_scores) * 0.52
    selected_rows = [y for score, y in row_scores if score >= threshold and score > 30]
    if not selected_rows:
        return None
    center = max(row_scores)[1]
    selected_rows = [y for y in selected_rows if abs(y - center) <= height * 0.1]
    top, bottom = min(selected_rows), max(selected_rows) + step
    column_scores: list[tuple[int, int]] = []
    for x in range(x_start, x_end, step):
        neutral = 0
        for y in range(top, bottom, step):
            red, green, blue = cast("tuple[int, int, int]", image.getpixel((x, y)))
            if 75 <= red <= 250 and max(red, green, blue) - min(red, green, blue) < 38:
                neutral += 1
        column_scores.append((neutral, x))
    column_threshold = max(4, round((bottom - top) / step * 0.18))
    selected_columns = [x for score, x in column_scores if score >= column_threshold]
    if not selected_columns:
        return None
    left, right = min(selected_columns), max(selected_columns) + step
    candidate = WindowBounds(x=left, y=top, width=right - left, height=bottom - top)
    if candidate.width < width * 0.12 or candidate.height < height * 0.035:
        return None
    return candidate


def _manage_teams_panel_bounds(image: Image.Image) -> WindowBounds | None:
    """Recognize the broad neutral grid of the version-pinned Manage Teams window."""
    width, height = image.size
    x_start, x_end = round(width * 0.02), round(width * 0.52)
    y_start, y_end = round(height * 0.15), round(height * 0.84)
    step = max(3, width // 756)
    selected_rows: list[tuple[int, tuple[int, ...]]] = []
    for y in range(y_start, y_end, step):
        neutral_x: list[int] = []
        for x in range(x_start, x_end, step):
            red, green, blue = cast("tuple[int, int, int]", image.getpixel((x, y)))
            if 70 <= red <= 235 and max(red, green, blue) - min(red, green, blue) < 28:
                neutral_x.append(x)
        if len(neutral_x) * step >= width * 0.24:
            selected_rows.append((y, tuple(neutral_x)))
    if not selected_rows:
        return None
    groups: list[list[tuple[int, tuple[int, ...]]]] = []
    for row in selected_rows:
        if not groups or row[0] - groups[-1][-1][0] > step * 2:
            groups.append([row])
        else:
            groups[-1].append(row)
    groups = [group for group in groups if len(group) * step >= height * 0.16]
    if not groups:
        return None
    group = max(groups, key=len)
    xs = [x for _, row_x in group for x in row_x]
    candidate = WindowBounds(
        x=min(xs),
        y=group[0][0],
        width=max(xs) - min(xs) + step,
        height=group[-1][0] - group[0][0] + step,
    )
    if candidate.width < width * 0.28:
        return None
    return candidate


def _team_tutorial_modal_present(image: Image.Image, *, panel: WindowBounds | None) -> bool:
    if panel is None:
        return False
    width, height = image.size
    step = max(3, width // 756)
    blue = 0
    light = 0
    for y in range(round(height * 0.34), round(height * 0.65), step):
        for x in range(round(width * 0.35), round(width * 0.65), step):
            red, green, value_blue = cast("tuple[int, int, int]", image.getpixel((x, y)))
            if value_blue > 95 and value_blue > red * 1.3 and value_blue > green * 1.08:
                blue += 1
            if (
                min(red, green, value_blue) > 150
                and max(red, green, value_blue) - min(red, green, value_blue) < 32
            ):
                light += 1
    return blue >= 8 and light >= 80


def _blocking_panel_bounds(
    image: Image.Image, *, known_panel: WindowBounds | None
) -> WindowBounds | None:
    if known_panel is not None:
        return None
    width, height = image.size
    # Fail closed on a large, nearly uniform central overlay; gameplay itself is highly textured.
    samples: list[tuple[int, int, int]] = []
    step = max(4, width // 500)
    for y in range(round(height * 0.3), round(height * 0.7), step):
        for x in range(round(width * 0.3), round(width * 0.7), step):
            samples.append(cast("tuple[int, int, int]", image.getpixel((x, y))))
    if not samples:
        return None
    quantized = {(red // 24, green // 24, blue // 24) for red, green, blue in samples}
    if len(quantized) > 24:
        return None
    left = round(width * 0.3)
    right = round(width * 0.7)
    top = round(height * 0.3)
    bottom = round(height * 0.7)
    gap = step * 2

    def strongly_separated(first: tuple[int, int, int], second: tuple[int, int, int]) -> bool:
        return (
            sum(
                (left_value - right_value) ** 2
                for left_value, right_value in zip(first, second, strict=True)
            )
            > 45**2
        )

    edge_pairs = (
        ((x, top + gap, x, top - gap) for x in range(left, right, step)),
        ((x, bottom - gap, x, bottom + gap) for x in range(left, right, step)),
        ((left + gap, y, left - gap, y) for y in range(top, bottom, step)),
        ((right - gap, y, right + gap, y) for y in range(top, bottom, step)),
    )
    strong_edges = 0
    for pairs in edge_pairs:
        comparisons = tuple(pairs)
        separated = sum(
            strongly_separated(
                cast("tuple[int, int, int]", image.getpixel((x1, y1))),
                cast("tuple[int, int, int]", image.getpixel((x2, y2))),
            )
            for x1, y1, x2, y2 in comparisons
        )
        if comparisons and separated / len(comparisons) >= 0.35:
            strong_edges += 1
    if strong_edges < 3:
        return None
    return WindowBounds(
        x=left,
        y=top,
        width=right - left,
        height=bottom - top,
    )


def _manage_teams_target(
    capture: CapturedDesktopFrame,
    toolbar: WindowBounds,
    button: tuple[int, int, int],
    scene: SoftwareIncUIScene,
    projection_id: str,
    expires_at: datetime,
) -> VisualTarget:
    return _management_toolbar_target(
        capture,
        button,
        scene,
        projection_id,
        expires_at,
        target_id="manage_teams_button",
        control_name="Manage teams",
    )


def _management_toolbar_target(
    capture: CapturedDesktopFrame,
    button: tuple[int, int, int],
    scene: SoftwareIncUIScene,
    projection_id: str,
    expires_at: datetime,
    *,
    target_id: str,
    control_name: str,
) -> VisualTarget:
    score, pixel_x, pixel_y = button
    scale = capture.metadata.display_scale
    logical_x = capture.metadata.window_bounds.x + round(pixel_x / scale)
    logical_y = capture.metadata.window_bounds.y + round(pixel_y / scale)
    inset = max(2, round(12 / scale))
    region = WindowBounds(
        x=logical_x - inset,
        y=logical_y - inset,
        width=inset * 2 + 1,
        height=inset * 2 + 1,
    )
    return VisualTarget(
        target_id=target_id,
        source_frame_id=capture.metadata.frame_id,
        point=ScreenPoint(x=logical_x, y=logical_y),
        region=region,
        scene=scene,
        projection_id=projection_id,
        confidence=min(0.98, 0.82 + score / 1000),
        evidence=(
            "bottom-left management toolbar visually anchored in current frame",
            f"version 1.8.41 {control_name} HR button visually matched",
            "target derived from a bounded current-frame feature search and Retina scale",
        ),
        expires_at=expires_at,
    )


def _manage_teams_button_peak(image: Image.Image) -> tuple[int, int, int] | None:
    """Find the HR group icon inside a version-scoped region, never a fixed point."""
    # Bound the search to the third control in the visually anchored HR group;
    # extending into the neighboring Logistics group can produce a stronger
    # but semantically wrong icon match.
    return _management_button_peak(image, x_start_ratio=0.121, x_end_ratio=0.133)


def known_nonblocking_help_tip(snapshot: GameSnapshot | None) -> bool:
    """Expose the semantic non-blocking help-tip rule for contract tests."""
    return _known_nonblocking_help_tip(snapshot)


def semantic_blocking_dialog(snapshot: GameSnapshot | None) -> bool:
    """Expose the semantic blocking-dialog rule for contract tests."""
    return _semantic_blocking_dialog(snapshot)


def _hire_employees_button_peak(image: Image.Image) -> tuple[int, int, int] | None:
    """Find the adjacent Hire employees icon from current toolbar pixels."""
    return _management_button_peak(image, x_start_ratio=0.112, x_end_ratio=0.118)


def _management_button_peak(
    image: Image.Image,
    *,
    x_start_ratio: float,
    x_end_ratio: float,
) -> tuple[int, int, int] | None:
    width, height = image.size
    x_start, x_end = round(width * x_start_ratio), round(width * x_end_ratio)
    # The HR heading occupies the band immediately above the controls.  Search
    # the icon row itself so a high-contrast heading can never be mistaken for
    # an actionable button.
    y_start, y_end = round(height * 0.825), round(height * 0.848)
    radius = max(12, round(width * 0.011))
    step = max(2, width // 1512)
    candidates: list[tuple[int, int, int]] = []
    for center_y in range(y_start, y_end, step * 2):
        for center_x in range(x_start, x_end, step * 2):
            score = 0
            for offset_x, offset_y in (
                (-radius, 0),
                (radius, 0),
                (0, -radius),
                (0, radius),
                (-radius // 2, -radius // 2),
                (radius // 2, -radius // 2),
                (-radius // 2, radius // 2),
                (radius // 2, radius // 2),
            ):
                red, green, blue = cast(
                    "tuple[int, int, int]",
                    image.getpixel((center_x + offset_x, center_y + offset_y)),
                )
                neutral_ring = (
                    min(red, green, blue) > 145
                    and max(red, green, blue) - min(red, green, blue) < 45
                )
                if neutral_ring:
                    score += 25
            dark = 0
            sample_step = max(2, radius // 5)
            for offset_x in range(-radius // 2, radius // 2 + 1, sample_step):
                for offset_y in range(-radius // 2, radius // 2 + 1, sample_step):
                    red, green, blue = cast(
                        "tuple[int, int, int]",
                        image.getpixel((center_x + offset_x, center_y + offset_y)),
                    )
                    if max(red, green, blue) < 105:
                        dark += 1
            candidates.append((score + dark * 5, center_x, center_y))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    best = candidates[0]
    if best[0] < 180:
        return None
    separated = [
        candidate
        for candidate in candidates[1:]
        if abs(candidate[1] - best[1]) > radius or abs(candidate[2] - best[2]) > radius
    ]
    if separated and separated[0][0] >= best[0] * 0.98:
        return None
    return best


def _projection_id(
    capture: CapturedDesktopFrame,
    toolbar: WindowBounds | None,
    active_time_button: WindowBounds | None,
    management_panel: WindowBounds | None,
    *,
    staffing_targets: tuple[VisualTarget, ...] = (),
) -> str:
    parts = [
        capture.metadata.window_id,
        str(capture.metadata.window_bounds.model_dump(mode="json")),
        f"{capture.metadata.pixel_width}x{capture.metadata.pixel_height}",
        str(None if toolbar is None else toolbar.model_dump(mode="json")),
        str(None if active_time_button is None else active_time_button.model_dump(mode="json")),
        str(None if management_panel is None else management_panel.model_dump(mode="json")),
        str(
            tuple(
                (
                    target.target_id,
                    None if target.point is None else target.point.model_dump(mode="json"),
                    target.confidence,
                )
                for target in staffing_targets
            )
        ),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


__all__ = ["recognize_ui"]
