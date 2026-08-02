"""Prompt 7 Atlas policy, workflow, persistence, and intent tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import stat
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
from sim_pilot.software_inc.products import (
    ProductIntentAction,
    ProductStage,
    ProductWorkflowStatus,
    ProductWorkflowStore,
    advance_product,
    close_product_configuration,
    iterate_product,
    operating_system_options,
    parse_product_intent,
    recommend_atlas,
    review_product,
    set_product_hold,
    store_is_owner_only,
)
from sim_pilot.software_inc.products import operator as product_operator
from sim_pilot.software_inc.products.operator import promote_product, start_atlas
from sim_pilot.software_inc.products.projection import observed_stage
from sim_pilot.software_inc.products.workflow import (
    create_workflow,
    resolve_approval,
    synchronize_workflow,
)
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    VisualTarget,
)
from sim_pilot.software_inc.ui.observer import ObservedSoftwareIncUI
from sim_pilot.software_inc.ui.recognition import (
    _semantic_target_id,  # pyright: ignore[reportPrivateUsage]
)


class _Backend:
    def __init__(self) -> None:
        self.gestures: list[tuple[InputGesture, DesktopFrame]] = []

    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> None:
        self.gestures.append((gesture, frame))


class _Observer:
    def __init__(self, observations: list[ObservedSoftwareIncUI]) -> None:
        self.observations = observations
        self.backend = _Backend()
        self.foreground_calls = 0

    async def observe(self) -> ObservedSoftwareIncUI:
        if not self.observations:
            raise AssertionError("operator requested an unexpected observation")
        return self.observations.pop(0)

    async def keep_game_foreground(self) -> None:
        self.foreground_calls += 1


def _surface(
    name: str,
    entities: tuple[ObservedEntity, ...] = (),
    *,
    status: CoverageStatus = CoverageStatus.OBSERVED_COMPLETE,
) -> ObservationSurface:
    return ObservationSurface(
        coverage=FieldCoverage(surface=name, status=status, fields=()),
        entities=entities,
    )


def product_snapshot(
    sequence: int = 10,
    *,
    cash: float = 60_000,
    product_scene: str = "product_configuration",
    product_name: str = "Atlas",
    selected_features: str = "2D graphics|System",
    selected_operating_systems: str = "44:Orchard System 2",
    server_requirement: float = 0,
    active_work: bool = False,
    stage: ProductStage | None = None,
    held: bool = False,
    progress: float = 0,
    iteration: int = 0,
    game_paused: bool = True,
    linked_review: bool = False,
    review_cost_text: str = "",
) -> GameSnapshot:
    existing_work: tuple[ObservedEntity, ...] = ()
    if active_work or stage is not None:
        existing_work = (
            ObservedEntity(
                entity_type="work_item",
                entity_id="701",
                values={
                    "assigned_teams": "Core",
                    "done": False,
                    "in_beta": stage is ProductStage.BETA,
                    "is_contract": False,
                    "iteration": iteration,
                    "name": "Atlas" if stage is not None else "Existing Work",
                    "paused": held,
                    "progress": progress,
                    "review_accuracy": 0.7,
                    "review_score": 0.65,
                    "work_type": (
                        "Design" if stage in {None, ProductStage.DESIGN} else "Development"
                    ),
                },
            ),
        )
        if linked_review:
            existing_work += (
                ObservedEntity(
                    entity_type="work_item",
                    entity_id="800",
                    values={
                        "name": "Peer review",
                        "progress": 0.2,
                        "review_target_work_item_id": "701",
                        "stage": "Review in progress",
                    },
                ),
            )
    catalog = (
        ObservedEntity(
            entity_type="software_category",
            entity_id="2D Editor:Default",
            values={
                "description": "",
                "ideal_price": 80.0,
                "is_default": True,
                "name": "Default",
                "product_type": "2D Editor",
                "unlocked": True,
            },
        ),
        ObservedEntity(
            entity_type="software_feature",
            entity_id="2D Editor:2D graphics",
            values={
                "code_art_ratio": 0.8,
                "dependencies": "",
                "development_time": 6.0,
                "localized_name": "2D graphics",
                "product_type": "2D Editor",
                "server_requirement": 0.0,
                "specialization": "2D",
                "unlocked": True,
            },
        ),
        ObservedEntity(
            entity_type="software_feature",
            entity_id="2D Editor:System",
            values={
                "code_art_ratio": 1.0,
                "dependencies": "",
                "development_time": 2.0,
                "localized_name": "System",
                "product_type": "2D Editor",
                "server_requirement": server_requirement,
                "specialization": "System",
                "unlocked": True,
            },
        ),
        ObservedEntity(
            entity_type="software_type",
            entity_id="2D Editor",
            values={
                "categories": "Default",
                "description": "Program that allows you to handle 2D color arrays",
                "in_house": True,
                "name": "2D Editor",
                "optimal_development_time": 35.0,
                "os_specific": True,
                "unlocked": True,
            },
        ),
    )
    ui_state = ObservedEntity(
        entity_type="product_ui_state",
        entity_id="current",
        values={
            "design_teams": "Core",
            "development_teams": "Core",
            "current_page": 0,
            "price": 80.0,
            "product_name": product_name,
            "scene": product_scene,
            "selected_category": "Default",
            "selected_features": selected_features,
            "selected_operating_systems": selected_operating_systems,
            "selected_type": "2D Editor",
            "team_issue": "",
            "available_operating_systems": "44:Orchard System 2",
        },
    )
    return GameSnapshot(
        capture_timestamp=datetime.now(UTC),
        capture_started_marker="main-thread",
        capture_completed_marker="main-thread",
        bridge_sequence=sequence,
        bridge_instance_id="bridge-v10",
        game_session_id="product-session",
        game_id="software-inc",
        game_version="1.8.41",
        adapter_version="software-inc-readonly-v10",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        map_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="not applicable"),
        save_identity=Identity(status=IdentityStatus.OBSERVED, value="product-save"),
        game_state={
            "force_pause": game_paused,
            "simulation_speed": "0" if game_paused else "1",
        },
        surfaces=(
            _surface(
                "contract_ui",
                (
                    ObservedEntity(
                        entity_type="contract_ui_state",
                        entity_id="current",
                        values={"review_cost_text": review_cost_text},
                    ),
                ),
            ),
            _surface(
                "education",
                (
                    ObservedEntity(
                        entity_type="employee_specialization",
                        entity_id="100:Designer:2D",
                        values={
                            "employee_id": "100",
                            "level": 2,
                            "role": "Designer",
                            "specialization": "2D",
                        },
                    ),
                    ObservedEntity(
                        entity_type="employee_specialization",
                        entity_id="100:Designer:System",
                        values={
                            "employee_id": "100",
                            "level": 2,
                            "role": "Designer",
                            "specialization": "System",
                        },
                    ),
                    ObservedEntity(
                        entity_type="employee_specialization",
                        entity_id="100:Programmer:2D",
                        values={
                            "employee_id": "100",
                            "level": 2,
                            "role": "Programmer",
                            "specialization": "2D",
                        },
                    ),
                    ObservedEntity(
                        entity_type="employee_specialization",
                        entity_id="100:Programmer:System",
                        values={
                            "employee_id": "100",
                            "level": 2,
                            "role": "Programmer",
                            "specialization": "System",
                        },
                    ),
                ),
            ),
            _surface(
                "employees",
                (
                    ObservedEntity(
                        entity_type="employee",
                        entity_id="100",
                        values={
                            "name": "Alex Founder",
                            "salary": 1_000.0,
                            "skill_artist": 0.1,
                            "skill_designer": 0.8,
                            "skill_programmer": 0.8,
                            "team": "Core",
                        },
                    ),
                ),
            ),
            _surface(
                "finances",
                (
                    ObservedEntity(
                        entity_type="company_finances",
                        entity_id="company",
                        values={"cash": cash},
                    ),
                ),
                status=CoverageStatus.OBSERVED_PARTIAL,
            ),
            _surface("infrastructure"),
            _surface("product_catalog", catalog),
            _surface(
                "product_ui",
                (
                    ObservedEntity(
                        entity_type="operating_system_option",
                        entity_id="44",
                        values={
                            "name": "Orchard System 2",
                            "release_date": "January 1980",
                            "selected": bool(selected_operating_systems),
                            "userbase": 125_000,
                        },
                    ),
                    ui_state,
                ),
            ),
            _surface(
                "teams",
                (
                    ObservedEntity(
                        entity_type="team",
                        entity_id="Core",
                        values={"employee_count": 1, "name": "Core"},
                    ),
                ),
            ),
            _surface("work_items", existing_work),
        ),
    )


def _observed(
    snapshot: GameSnapshot,
    scene: SoftwareIncUIScene,
    *,
    target_ids: tuple[str, ...] = (),
    modal: ModalState = ModalState.NONE,
) -> ObservedSoftwareIncUI:
    sequence = snapshot.bridge_sequence
    image = Image.new("RGB", (100, 100), "gray")
    frame_id = hashlib.sha256(f"product-frame:{sequence}".encode()).hexdigest()
    frame = DesktopFrame(
        frame_id=frame_id,
        capture_sequence=sequence,
        captured_at=datetime.now(UTC),
        process_id=77,
        window_id="software-inc-window",
        window_title="Software Inc.",
        window_bounds=WindowBounds(x=0, y=0, width=100, height=100),
        window_frontmost=True,
        pixel_width=100,
        pixel_height=100,
        display_scale=1,
        sha256=hashlib.sha256(image.tobytes()).hexdigest(),
        platform="macos",
    )
    targets = tuple(
        VisualTarget(
            target_id=target_id,
            source_frame_id=frame.frame_id,
            point=ScreenPoint(x=50, y=50),
            scene=scene,
            projection_id="a" * 64,
            confidence=0.99,
            evidence=("exact semantic fixture",),
            expires_at=datetime.now(UTC) + timedelta(seconds=30),
        )
        for target_id in target_ids
    )
    observation = SoftwareIncUIObservation(
        semantic_before=snapshot,
        semantic_after=snapshot,
        frame=frame,
        scene=scene,
        modal_state=modal,
        projection_id="a" * 64,
        targets=targets,
        synchronization_started_at=datetime.now(UTC),
        synchronization_completed_at=datetime.now(UTC),
        synchronization_duration_seconds=0,
        semantic_capture_skew_seconds=0,
    )
    return ObservedSoftwareIncUI(observation, CapturedDesktopFrame(frame, image))


def test_atlas_recommendation_is_bounded_and_excludes_forecast_revenue() -> None:
    recommendation = recommend_atlas(product_snapshot())

    assert recommendation.recommended
    assert recommendation.configuration.name == "Atlas"
    assert recommendation.configuration.product_type == "2D Editor"
    assert recommendation.configuration.category == "Default"
    assert recommendation.configuration.features == ("2D graphics", "System")
    assert recommendation.configuration.price == Decimal("80.0")
    assert recommendation.configuration.operating_systems == ("44:Orchard System 2",)
    assert recommendation.configuration.design_teams == ("Core",)
    assert recommendation.runway.observed_cash == Decimal("60000.0")
    assert recommendation.runway.conservative_months == Decimal("8")
    assert recommendation.runway.conservative_recurring_cost == Decimal("8000.0")
    assert recommendation.runway.projected_cash_after == Decimal("52000.0")
    assert recommendation.runway.forecast_revenue_included is False
    assert recommendation.team.relevant_specializations == ("2D", "System")
    assert "Forecast sales" in recommendation.material_unknowns[1]
    assert operating_system_options(product_snapshot())[0].userbase == 125_000


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (product_snapshot(cash=51_000), "reserve"),
        (product_snapshot(active_work=True), "active work"),
        (product_snapshot(server_requirement=1), "server requirement"),
        (product_snapshot(product_name="Other"), "exactly Atlas"),
    ],
)
def test_policy_rejects_unsafe_or_nonexact_configuration(
    snapshot: GameSnapshot, reason: str
) -> None:
    recommendation = recommend_atlas(snapshot)

    assert not recommendation.recommended
    assert any(reason in item for item in recommendation.reasons)


def test_workflow_requires_approval_and_reconciles_design_alpha_beta() -> None:
    initial = product_snapshot()
    recommendation = recommend_atlas(initial)
    workflow = create_workflow(initial, recommendation)
    assert workflow.status is ProductWorkflowStatus.WAITING_FOR_APPROVAL
    assert workflow.pending_approval is not None
    approved = resolve_approval(workflow, approved=True)

    design = synchronize_workflow(
        approved, product_snapshot(11, stage=ProductStage.DESIGN, progress=0.3)
    )
    assert design.stage is ProductStage.DESIGN
    assert design.progress == Decimal("0.3")
    alpha = synchronize_workflow(
        design, product_snapshot(12, stage=ProductStage.ALPHA, progress=0.1, iteration=1)
    )
    assert alpha.stage is ProductStage.ALPHA
    assert alpha.iteration == 1
    beta = synchronize_workflow(
        alpha, product_snapshot(13, stage=ProductStage.BETA, progress=0.7, iteration=1)
    )
    assert beta.stage is ProductStage.BETA
    assert beta.status is ProductWorkflowStatus.BETA_REACHED
    with pytest.raises(SoftwareIncUIValidationError, match="fresh bridge sequence"):
        synchronize_workflow(beta, product_snapshot(13, stage=ProductStage.BETA))


def test_observed_stage_matches_supported_1841_lifecycle() -> None:
    assert (
        observed_stage(product_snapshot(stage=ProductStage.DESIGN).surfaces[-1].entities[0])
        is ProductStage.DESIGN
    )
    assert (
        observed_stage(product_snapshot(stage=ProductStage.ALPHA).surfaces[-1].entities[0])
        is ProductStage.ALPHA
    )
    assert (
        observed_stage(product_snapshot(stage=ProductStage.BETA).surfaces[-1].entities[0])
        is ProductStage.BETA
    )


def test_owner_only_store_enforces_one_open_product_per_save(tmp_path: Path) -> None:
    snapshot = product_snapshot()
    workflow = create_workflow(snapshot, recommend_atlas(snapshot))
    store = ProductWorkflowStore(tmp_path / "products.sqlite3")
    store.save(workflow)
    identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)

    assert store.current(game_session_id="product-session", save_identity=identity) == workflow
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store_is_owner_only(store.path)

    conflicting = workflow.model_copy(update={"workflow_id": workflow.workflow_id.__class__(int=2)})
    with pytest.raises(SoftwareIncUIValidationError, match="another open product workflow"):
        store.save(conflicting)


def test_plain_english_product_intents_are_strict_and_bounded() -> None:
    intent = parse_product_intent(
        "begin a small 2D Editor called Atlas using Core and keep $50,000 in reserve"
    )
    assert intent.action is ProductIntentAction.CREATE
    assert intent.product_name == "Atlas"
    assert intent.product_type == "2D Editor"
    assert intent.requested_product_type == "2D Editor"
    assert not intent.mapping_note
    assert intent.team_name == "Core"
    assert intent.minimum_cash_reserve == Decimal("50000")
    assert parse_product_intent("hold Atlas").action is ProductIntentAction.HOLD
    assert parse_product_intent("resume Atlas").action is ProductIntentAction.RESUME
    with pytest.raises(SoftwareIncUIValidationError, match="explicit product type"):
        parse_product_intent("create Atlas")
    with pytest.raises(SoftwareIncUIValidationError, match="unsupported product intent"):
        parse_product_intent("release Atlas")


def test_product_target_identity_distinguishes_teams_and_expands_work() -> None:
    assert (
        _semantic_target_id(
            "product-button-1",
            scene=SoftwareIncUIScene.PRODUCT_CONFIGURATION,
            label="Design Team",
            object_name="ChangeTeamButton",
            path="Canvas/DesignDocumentWindow/DesignTeam",
            callbacks="DesignDocumentWindow.ChangeDevTeam",
        )
        == "choose_product_design_team"
    )
    assert (
        _semantic_target_id(
            "product-button-2",
            scene=SoftwareIncUIScene.PRODUCT_CONFIGURATION,
            label="Development Team",
            object_name="ChangeTeamButton",
            path="Canvas/DesignDocumentWindow/DevTeam",
            callbacks="DesignDocumentWindow.ChangeDevTeam",
        )
        == "choose_product_development_team"
    )
    assert (
        _semantic_target_id(
            "work-item-701-button-0",
            scene=SoftwareIncUIScene.GAMEPLAY_PAUSED,
            label="",
            object_name="ExpandIcon",
            path="Canvas/Work/Atlas/ExpandIcon",
            callbacks="GUIWorkItem.ToggleOpen",
        )
        == "work-item-701-open"
    )


def test_start_dry_run_and_denied_approval_send_no_input(tmp_path: Path) -> None:
    gameplay = product_snapshot(product_scene="gameplay")
    dry_observer = _Observer(
        [
            _observed(
                gameplay,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("open_product_design",),
            )
        ]
    )
    result = asyncio.run(
        start_atlas(
            dry_run=True,
            observer_factory=lambda: dry_observer,
            store=ProductWorkflowStore(tmp_path / "dry.sqlite3"),
        )
    )
    assert result.partial
    assert result.gestures_sent == 0
    assert dry_observer.backend.gestures == []
    dry_identity = json.dumps(gameplay.save_identity.model_dump(mode="json"), sort_keys=True)
    assert (
        ProductWorkflowStore(tmp_path / "dry.sqlite3").current(
            game_session_id=gameplay.game_session_id, save_identity=dry_identity
        )
        is None
    )

    configured = product_snapshot(11)
    denied_observer = _Observer(
        [
            _observed(
                configured,
                SoftwareIncUIScene.PRODUCT_CONFIGURATION,
                target_ids=("commit_product_design",),
            )
        ]
    )
    denied = asyncio.run(
        start_atlas(
            approval_provider=lambda _approval: False,
            observer_factory=lambda: denied_observer,
            store=ProductWorkflowStore(tmp_path / "denied.sqlite3"),
        )
    )
    assert not denied.verified
    assert not denied.partial
    assert denied.workflow is not None
    assert denied.workflow.status is ProductWorkflowStatus.FAILED
    assert denied.gestures_sent == 0
    assert denied_observer.backend.gestures == []


def test_start_does_not_retry_open_product_design_without_verified_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(product_operator, "_SETTLE_SECONDS", 0)
    observer = _Observer(
        [
            _observed(
                product_snapshot(8, product_scene="gameplay", product_name=""),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("open_product_design",),
            ),
            _observed(
                product_snapshot(9, product_scene="gameplay", product_name=""),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("open_product_design",),
            ),
        ]
    )

    with pytest.raises(SoftwareIncUIVerificationError, match="no retry attempted"):
        asyncio.run(
            start_atlas(
                approval_provider=lambda _approval: True,
                observer_factory=lambda: observer,
                store=ProductWorkflowStore(tmp_path / "no-retry.sqlite3"),
            )
        )

    assert [gesture.target_id for gesture, _frame in observer.backend.gestures] == [
        "open_product_design"
    ]


def test_close_product_configuration_is_one_verified_reversible_gesture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(product_operator, "_SETTLE_SECONDS", 0)
    observer = _Observer(
        [
            _observed(
                product_snapshot(14),
                SoftwareIncUIScene.PRODUCT_CONFIGURATION,
                target_ids=("close_product_configuration",),
            ),
            _observed(
                product_snapshot(15, product_scene="gameplay", product_name=""),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            ),
        ]
    )

    result = asyncio.run(close_product_configuration(observer_factory=lambda: observer))

    assert result.verified and result.gestures_sent == 1
    assert [gesture.target_id for gesture, _frame in observer.backend.gestures] == [
        "close_product_configuration"
    ]


def test_start_preflight_selects_only_observed_bounded_feature_and_audience_os(
    tmp_path: Path,
) -> None:
    feature_observer = _Observer(
        [
            _observed(
                product_snapshot(12, selected_features="2D graphics"),
                SoftwareIncUIScene.PRODUCT_CONFIGURATION,
                target_ids=("product_feature_System",),
            )
        ]
    )
    feature = asyncio.run(
        start_atlas(
            dry_run=True,
            observer_factory=lambda: feature_observer,
            store=ProductWorkflowStore(tmp_path / "feature.sqlite3"),
        )
    )
    assert feature.partial and feature.gestures_sent == 0
    assert "bounded feature 'System'" in feature.message

    os_observer = _Observer(
        [
            _observed(
                product_snapshot(13, selected_operating_systems=""),
                SoftwareIncUIScene.PRODUCT_CONFIGURATION,
                target_ids=("product_os_44",),
            )
        ]
    )
    operating_system = asyncio.run(
        start_atlas(
            dry_run=True,
            observer_factory=lambda: os_observer,
            store=ProductWorkflowStore(tmp_path / "os.sqlite3"),
        )
    )
    assert operating_system.partial and operating_system.gestures_sent == 0
    assert "Orchard System 2" in operating_system.message
    assert "125,000" in operating_system.message
    assert os_observer.backend.gestures == []


def test_start_atlas_commits_once_verifies_and_rejects_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(product_operator, "_SETTLE_SECONDS", 0)
    store = ProductWorkflowStore(tmp_path / "creation.sqlite3")
    observer = _Observer(
        [
            _observed(
                product_snapshot(20),
                SoftwareIncUIScene.PRODUCT_CONFIGURATION,
                target_ids=("commit_product_design",),
            ),
            _observed(
                product_snapshot(21),
                SoftwareIncUIScene.PRODUCT_CONFIGURATION,
                target_ids=("commit_product_design",),
            ),
            _observed(
                product_snapshot(22, product_scene="gameplay", stage=ProductStage.DESIGN),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            ),
        ]
    )

    created = asyncio.run(
        start_atlas(
            approval_provider=lambda _approval: True,
            observer_factory=lambda: observer,
            store=store,
        )
    )

    assert created.verified
    assert not created.partial
    assert created.workflow is not None
    assert created.workflow.stage is ProductStage.DESIGN
    assert created.workflow.work_item_id == "701"
    assert created.event is not None
    assert created.event.event_type == "product_created"
    assert created.gestures_sent == 1
    assert [item[0].target_id for item in observer.backend.gestures] == ["commit_product_design"]

    duplicate_observer = _Observer(
        [
            _observed(
                product_snapshot(23, product_scene="gameplay", stage=ProductStage.DESIGN),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            )
        ]
    )
    duplicate = asyncio.run(start_atlas(observer_factory=lambda: duplicate_observer, store=store))
    assert duplicate.verified
    assert duplicate.gestures_sent == 0
    assert "already exists" in duplicate.message
    assert duplicate_observer.backend.gestures == []


def _active_workflow(sequence: int = 40):
    initial = product_snapshot(sequence)
    workflow = resolve_approval(create_workflow(initial, recommend_atlas(initial)), approved=True)
    return synchronize_workflow(
        workflow,
        product_snapshot(sequence + 1, product_scene="gameplay", stage=ProductStage.DESIGN),
    )


def test_hold_resume_and_bounded_advance_verify_each_fresh_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(product_operator, "_SETTLE_SECONDS", 0)
    workflow = _active_workflow()
    store = ProductWorkflowStore(tmp_path / "control.sqlite3")
    store.save(workflow)
    hold_observer = _Observer(
        [
            _observed(
                product_snapshot(42, product_scene="gameplay", stage=ProductStage.DESIGN),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("work-item-701-toggle-pause",),
            ),
            _observed(
                product_snapshot(
                    43,
                    product_scene="gameplay",
                    stage=ProductStage.DESIGN,
                    held=True,
                ),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            ),
        ]
    )
    held = asyncio.run(
        set_product_hold(
            workflow,
            held=True,
            observer_factory=lambda: hold_observer,
            store=store,
        )
    )
    assert held.verified and held.workflow is not None and held.workflow.held
    assert held.gestures_sent == 1

    resume_observer = _Observer(
        [
            _observed(
                product_snapshot(
                    44,
                    product_scene="gameplay",
                    stage=ProductStage.DESIGN,
                    held=True,
                ),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("work-item-701-toggle-pause",),
            ),
            _observed(
                product_snapshot(45, product_scene="gameplay", stage=ProductStage.DESIGN),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            ),
        ]
    )
    resumed = asyncio.run(
        set_product_hold(
            held.workflow,
            held=False,
            observer_factory=lambda: resume_observer,
            store=store,
        )
    )
    assert resumed.verified and resumed.workflow is not None and not resumed.workflow.held

    advance_observer = _Observer(
        [
            _observed(
                product_snapshot(
                    46, product_scene="gameplay", stage=ProductStage.DESIGN, progress=0.1
                ),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("resume_button",),
            ),
            _observed(
                product_snapshot(
                    47,
                    product_scene="gameplay",
                    stage=ProductStage.DESIGN,
                    progress=0.1,
                    game_paused=False,
                ),
                SoftwareIncUIScene.GAMEPLAY_RUNNING,
            ),
            _observed(
                product_snapshot(
                    48,
                    product_scene="gameplay",
                    stage=ProductStage.DESIGN,
                    progress=0.2,
                    game_paused=False,
                ),
                SoftwareIncUIScene.GAMEPLAY_RUNNING,
                target_ids=("pause_button",),
            ),
            _observed(
                product_snapshot(
                    49, product_scene="gameplay", stage=ProductStage.DESIGN, progress=0.3
                ),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            ),
        ]
    )
    advanced = asyncio.run(
        advance_product(
            resumed.workflow,
            run_seconds=0.001,
            observer_factory=lambda: advance_observer,
            store=store,
        )
    )
    assert advanced.verified and not advanced.partial
    assert advanced.workflow is not None and advanced.workflow.progress == Decimal("0.3")
    assert advanced.gestures_sent == 2
    assert advance_observer.foreground_calls == 1
    assert [item[0].target_id for item in advance_observer.backend.gestures] == [
        "resume_button",
        "pause_button",
    ]


def test_review_and_iteration_have_separate_approvals_and_linked_postconditions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(product_operator, "_SETTLE_SECONDS", 0)
    workflow = _active_workflow(50)
    store = ProductWorkflowStore(tmp_path / "review.sqlite3")
    store.save(workflow)
    approvals: list[object] = []

    def approve(approval: object) -> bool:
        approvals.append(approval)
        return True

    review_observer = _Observer(
        [
            _observed(
                product_snapshot(52, product_scene="gameplay", stage=ProductStage.DESIGN),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("work-item-701-review",),
            ),
            _observed(
                product_snapshot(
                    53,
                    product_scene="gameplay",
                    stage=ProductStage.DESIGN,
                    review_cost_text="$500",
                ),
                SoftwareIncUIScene.CONTRACT_REVIEW_SETUP,
                target_ids=("commit_contract_review",),
            ),
            _observed(
                product_snapshot(
                    54,
                    product_scene="gameplay",
                    stage=ProductStage.DESIGN,
                    review_cost_text="$500",
                ),
                SoftwareIncUIScene.CONTRACT_REVIEW_SETUP,
                target_ids=("commit_contract_review",),
            ),
            _observed(
                product_snapshot(
                    55,
                    product_scene="gameplay",
                    stage=ProductStage.DESIGN,
                    linked_review=True,
                    cash=59_500,
                ),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            ),
        ]
    )
    reviewed = asyncio.run(
        review_product(
            workflow,
            approval_provider=approve,
            observer_factory=lambda: review_observer,
            store=store,
        )
    )
    assert reviewed.verified and reviewed.partial and reviewed.workflow is not None
    assert reviewed.gestures_sent == 2
    assert len(approvals) == 1
    assert reviewed.event is not None and reviewed.event.event_type == "product_review_started"

    iteration_observer = _Observer(
        [
            _observed(
                product_snapshot(
                    56,
                    product_scene="gameplay",
                    stage=ProductStage.DESIGN,
                    cash=59_500,
                ),
                SoftwareIncUIScene.CONTRACT_REVIEW_RESULT,
                target_ids=("review_result_iterate",),
            ),
            _observed(
                product_snapshot(
                    57,
                    product_scene="gameplay",
                    stage=ProductStage.DESIGN,
                    cash=59_500,
                ),
                SoftwareIncUIScene.CONTRACT_REVIEW_RESULT,
                target_ids=("review_result_iterate",),
            ),
            _observed(
                product_snapshot(
                    58,
                    product_scene="gameplay",
                    stage=ProductStage.DESIGN,
                    iteration=1,
                    cash=59_500,
                ),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            ),
        ]
    )
    iterated = asyncio.run(
        iterate_product(
            reviewed.workflow,
            approval_provider=approve,
            observer_factory=lambda: iteration_observer,
            store=store,
        )
    )
    assert iterated.verified and iterated.workflow is not None
    assert iterated.workflow.iteration == 1
    assert iterated.gestures_sent == 1
    assert len(approvals) == 2
    assert iterated.event is not None and iterated.event.event_type == "product_iterated"


def test_promotions_require_fresh_approval_and_stop_at_beta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(product_operator, "_SETTLE_SECONDS", 0)
    initial = product_snapshot(30)
    workflow = resolve_approval(create_workflow(initial, recommend_atlas(initial)), approved=True)
    workflow = synchronize_workflow(
        workflow, product_snapshot(31, product_scene="gameplay", stage=ProductStage.DESIGN)
    )
    store = ProductWorkflowStore(tmp_path / "promotions.sqlite3")
    store.save(workflow)
    approval_count = 0

    def approve(_approval: object) -> bool:
        nonlocal approval_count
        approval_count += 1
        return True

    alpha_observer = _Observer(
        [
            _observed(
                product_snapshot(32, product_scene="gameplay", stage=ProductStage.DESIGN),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("work-item-701-promote",),
            ),
            _observed(
                product_snapshot(33, product_scene="gameplay", stage=ProductStage.DESIGN),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("work-item-701-promote",),
            ),
            _observed(
                product_snapshot(34, product_scene="gameplay", stage=ProductStage.ALPHA),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            ),
        ]
    )
    alpha = asyncio.run(
        promote_product(
            workflow,
            approval_provider=approve,
            observer_factory=lambda: alpha_observer,
            store=store,
        )
    )
    assert alpha.workflow is not None
    assert alpha.workflow.stage is ProductStage.ALPHA
    assert alpha.gestures_sent == 1
    assert approval_count == 1

    beta_observer = _Observer(
        [
            _observed(
                product_snapshot(35, product_scene="gameplay", stage=ProductStage.ALPHA),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("work-item-701-promote",),
            ),
            _observed(
                product_snapshot(36, product_scene="gameplay", stage=ProductStage.ALPHA),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_ids=("work-item-701-promote",),
            ),
            _observed(
                product_snapshot(37, product_scene="gameplay", stage=ProductStage.BETA),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            ),
        ]
    )
    beta = asyncio.run(
        promote_product(
            alpha.workflow,
            approval_provider=approve,
            observer_factory=lambda: beta_observer,
            store=store,
        )
    )
    assert beta.workflow is not None
    assert beta.workflow.stage is ProductStage.BETA
    assert beta.workflow.status is ProductWorkflowStatus.BETA_REACHED
    assert beta.gestures_sent == 1
    assert approval_count == 2

    finished_observer = _Observer(
        [
            _observed(
                product_snapshot(38, product_scene="gameplay", stage=ProductStage.BETA),
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
            )
        ]
    )
    finished = asyncio.run(
        promote_product(
            beta.workflow,
            approval_provider=approve,
            observer_factory=lambda: finished_observer,
            store=store,
        )
    )
    assert finished.verified
    assert finished.gestures_sent == 0
    assert approval_count == 2
    assert "release is outside Prompt 7" in finished.message
