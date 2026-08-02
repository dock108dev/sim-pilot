"""One-gesture-per-cycle contract browser operator tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

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
from sim_pilot.software_inc.contracts.models import (
    ContractApproval,
    ContractCandidate,
    ContractRecommendation,
    ContractStage,
    ContractWorkflow,
    ContractWorkflowStatus,
    TeamContractAssessment,
)
from sim_pilot.software_inc.contracts.operator import (
    _review_cost,  # pyright: ignore[reportPrivateUsage]
    accept_recommended_contract,
    advance_contract,
    browse_contracts,
    promote_contract,
    release_contract,
    review_contract,
)
from sim_pilot.software_inc.contracts.projection import available_contracts
from sim_pilot.software_inc.contracts.store import ContractWorkflowStore
from sim_pilot.software_inc.errors import (
    SoftwareIncUIObservationError,
    SoftwareIncUIVerificationError,
)
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    VisualTarget,
)
from sim_pilot.software_inc.ui.observer import ObservedSoftwareIncUI


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


def _snapshot(sequence: int, *, market: bool) -> GameSnapshot:
    contract = ObservedEntity(
        entity_type="available_contract",
        entity_id="Acme|Utility",
        values={
            "added": "January",
            "art_ratio": 0.0,
            "client": "Acme",
            "deadline": "March",
            "days_remaining": 40.0,
            "dev_time": 1.0,
            "difficulty": 0.1,
            "display_index": 0,
            "features": "UI",
            "minimum_progress": 1.0,
            "months": 1,
            "name": "Utility",
            "penalty": 1000.0,
            "per_bug_penalty": 10.0,
            "quality_target": 0.5,
            "reward": 5000.0,
            "software_category": "Business",
            "software_type": "Utility",
            "status": "Available",
        },
    )
    market_surface = ObservationSurface(
        coverage=FieldCoverage(
            surface="contract_market",
            status=(CoverageStatus.OBSERVED_COMPLETE if market else CoverageStatus.UNAVAILABLE),
            fields=(),
            detail=None if market else "window closed",
        ),
        entities=(contract,) if market else (),
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
        map_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="none"),
        save_identity=Identity(status=IdentityStatus.OBSERVED, value="save"),
        game_state={"days_per_month": 20, "force_pause": True, "simulation_speed": "0"},
        surfaces=(market_surface,),
    )


def _observed(
    sequence: int,
    scene: SoftwareIncUIScene,
    *,
    target_id: str | None = None,
    market: bool = False,
    modal: ModalState = ModalState.NONE,
    snapshot: GameSnapshot | None = None,
) -> ObservedSoftwareIncUI:
    image = Image.new("RGB", (100, 100), "gray")
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    frame = DesktopFrame(
        frame_id=hashlib.sha256(f"frame:{sequence}".encode()).hexdigest(),
        capture_sequence=sequence,
        captured_at=datetime.now(UTC),
        process_id=77,
        window_id="window",
        window_title="Software Inc",
        window_bounds=WindowBounds(x=0, y=0, width=100, height=100),
        window_frontmost=True,
        pixel_width=100,
        pixel_height=100,
        display_scale=1,
        sha256=digest,
        platform="macos",
    )
    semantic_snapshot = snapshot or _snapshot(sequence, market=market)
    targets = ()
    if target_id is not None:
        targets = (
            VisualTarget(
                target_id=target_id,
                source_frame_id=frame.frame_id,
                point=ScreenPoint(x=50, y=50),
                scene=scene,
                projection_id="a" * 64,
                confidence=0.99,
                evidence=("fixture",),
                expires_at=datetime.now(UTC) + timedelta(seconds=30),
            ),
        )
    observation = SoftwareIncUIObservation(
        semantic_before=semantic_snapshot,
        semantic_after=semantic_snapshot,
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


def test_browse_contracts_uses_one_gesture_per_fresh_cycle() -> None:
    observer = _Observer(
        [
            _observed(1, SoftwareIncUIScene.GAMEPLAY_RUNNING, target_id="pause_button"),
            _observed(2, SoftwareIncUIScene.GAMEPLAY_PAUSED, target_id="open_contracts"),
            _observed(3, SoftwareIncUIScene.CONTRACT_BROWSER, market=True),
        ]
    )

    result = asyncio.run(browse_contracts(observer_factory=lambda: observer))

    assert result.verified
    assert result.gestures_sent == 2
    assert [item[0].target_id for item in observer.backend.gestures] == [
        "pause_button",
        "open_contracts",
    ]
    assert [item[0].expected_frame_id for item in observer.backend.gestures] == [
        hashlib.sha256(b"frame:1").hexdigest(),
        hashlib.sha256(b"frame:2").hexdigest(),
    ]


def test_browse_contracts_rejects_modal_without_input() -> None:
    observer = _Observer(
        [
            _observed(
                1,
                SoftwareIncUIScene.BLOCKING_MODAL,
                modal=ModalState.BLOCKING,
            )
        ]
    )

    with pytest.raises(SoftwareIncUIObservationError, match="modal state"):
        asyncio.run(browse_contracts(observer_factory=lambda: observer))

    assert observer.backend.gestures == []


def test_advance_dry_run_reports_contract_browser_preflight(tmp_path: Path) -> None:
    snapshot = _review_snapshot(2)
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.CONTRACT_BROWSER,
                target_id="close_contract_browser",
                snapshot=snapshot,
            )
        ]
    )

    result = asyncio.run(
        advance_contract(
            _workflow(snapshot),
            dry_run=True,
            observer_factory=lambda: observer,
            store=ContractWorkflowStore(tmp_path / "advance.sqlite3"),
        )
    )

    assert result.gestures_sent == 0
    assert result.partial
    assert "close the Contracts window" in result.message
    assert observer.backend.gestures == []


def test_advance_dry_run_reports_build_mode_preflight(tmp_path: Path) -> None:
    snapshot = _review_snapshot(2)
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.BUILD_MODE,
                target_id="open_build_mode",
                snapshot=snapshot,
            )
        ]
    )

    result = asyncio.run(
        advance_contract(
            _workflow(snapshot),
            dry_run=True,
            observer_factory=lambda: observer,
            store=ContractWorkflowStore(tmp_path / "advance-build.sqlite3"),
        )
    )

    assert result.gestures_sent == 0
    assert result.partial
    assert "close Build mode" in result.message
    assert observer.backend.gestures == []


def test_waiting_contract_requires_deadline_approval_before_activation(tmp_path: Path) -> None:
    snapshot = _review_snapshot(2, contract_started=False)
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_id="work-item-42-toggle-pause",
                snapshot=snapshot,
            )
        ]
    )
    approvals: list[ContractApproval] = []

    def deny(approval: ContractApproval) -> bool:
        approvals.append(approval)
        return False

    result = asyncio.run(
        advance_contract(
            _workflow(snapshot),
            deadline_risk_approval_provider=deny,
            observer_factory=lambda: observer,
            store=ContractWorkflowStore(tmp_path / "advance-start.sqlite3"),
        )
    )

    assert result.gestures_sent == 0
    assert not result.verified
    assert approvals[0].commitment.value == "deadline_risk"
    assert "Start or continue" in approvals[0].action_summary
    assert observer.backend.gestures == []


def test_waiting_contract_verifies_unpause_then_first_employee_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiting = _review_snapshot(2, contract_started=False, item_paused=True)
    approved = _review_snapshot(3, contract_started=False, item_paused=True)
    enabled = _review_snapshot(4, contract_started=False, item_paused=False)
    running = _review_snapshot(
        5,
        contract_started=False,
        item_paused=False,
        force_pause=False,
    )
    worked = _review_snapshot(
        6,
        contract_started=True,
        item_paused=False,
        force_pause=False,
        progress=0.1,
    )
    paused = _review_snapshot(
        7,
        contract_started=True,
        item_paused=False,
        progress=0.1,
    )
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_id="work-item-42-toggle-pause",
                snapshot=waiting,
            ),
            _observed(
                3,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_id="work-item-42-toggle-pause",
                snapshot=approved,
            ),
            _observed(
                4,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_id="resume_button",
                snapshot=enabled,
            ),
            _observed(5, SoftwareIncUIScene.GAMEPLAY_RUNNING, snapshot=running),
            _observed(
                6,
                SoftwareIncUIScene.GAMEPLAY_RUNNING,
                target_id="pause_button",
                snapshot=worked,
            ),
            _observed(7, SoftwareIncUIScene.GAMEPLAY_PAUSED, snapshot=paused),
        ]
    )

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("sim_pilot.software_inc.contracts.operator.asyncio.sleep", no_wait)
    store = ContractWorkflowStore(tmp_path / "advance-started.sqlite3")
    result = asyncio.run(
        advance_contract(
            _workflow(waiting),
            run_seconds=1,
            deadline_risk_approval_provider=lambda _approval: True,
            observer_factory=lambda: observer,
            store=store,
        )
    )

    assert result.verified
    assert result.workflow is not None
    assert result.gestures_sent == 3
    assert [gesture.target_id for gesture, _ in observer.backend.gestures] == [
        "work-item-42-toggle-pause",
        "resume_button",
        "pause_button",
    ]
    assert [event.event_type for event in store.events(result.workflow.workflow_id)] == [
        "contract_work_enabled",
        "ui_gesture",
        "ui_gesture",
        "work_interval_verified",
    ]
    assert observer.foreground_calls == 1


def _review_snapshot(
    sequence: int,
    *,
    review_setup: bool = False,
    linked_review: bool = False,
    linked_review_finished: bool = False,
    contract_started: bool | None = None,
    item_paused: bool = False,
    force_pause: bool = True,
    progress: float = 1.0,
    reviews_done: int = 0,
    review_score: float = 0.0,
) -> GameSnapshot:
    base = _snapshot(sequence, market=False)
    contract_work = ObservedEntity(
        entity_type="work_item",
        entity_id="42",
        values={
            "assigned_teams": "Core",
            "bugs": 3.0,
            "contract_client": "Acme",
            "contract_days_remaining": 20.0,
            "contract_deadline": "March",
            "contract_identity": "Acme|Utility",
            "contract_name": "Utility",
            "contract_penalty": 1000.0,
            "contract_reward": 5000.0,
            **({"contract_started": contract_started} if contract_started is not None else {}),
            "done": False,
            "employee_count": 2,
            "fixed_bugs": 0.0,
            "in_beta": False,
            "is_contract": True,
            "minimum_progress": 1.0,
            "paused": item_paused,
            "progress": progress,
            "released": False,
            "review_score": review_score,
            "reviews_done": reviews_done,
            "stage": "Alpha",
            "work_type": "Software Alpha",
        },
    )
    work = [contract_work]
    if linked_review:
        work.append(
            ObservedEntity(
                entity_type="work_item",
                entity_id="91",
                values={
                    "done": False,
                    "is_contract": False,
                    "progress": 1.0 if linked_review_finished else 0.0,
                    "review_target_work_item_id": "42",
                    "stage": "10 reviews finished" if linked_review_finished else "Reviewing",
                },
            )
        )
    contract_state = ObservedEntity(
        entity_type="contract_ui_state",
        entity_id="current",
        values={
            "review_client": bool(review_setup),
            "review_cost_text": "$1,250" if review_setup else "",
            "review_internal": True,
            "review_outsource": False,
            "review_slider_value": 5.0 if review_setup else 0.0,
            "scene": "contract_review_setup" if review_setup else "gameplay",
        },
    )
    return base.model_copy(
        update={
            "game_state": {
                **base.game_state,
                "force_pause": force_pause,
                "simulation_speed": "0" if force_pause else "1",
            },
            "surfaces": (
                *base.surfaces,
                ObservationSurface(
                    coverage=FieldCoverage(
                        surface="contract_ui",
                        status=CoverageStatus.OBSERVED_COMPLETE,
                        fields=(),
                    ),
                    entities=(contract_state,),
                ),
                ObservationSurface(
                    coverage=FieldCoverage(
                        surface="work_items",
                        status=CoverageStatus.OBSERVED_COMPLETE,
                        fields=(),
                    ),
                    entities=tuple(work),
                ),
            ),
        }
    )


def test_advance_finishes_completed_review_before_running_game_time(tmp_path: Path) -> None:
    initial = _review_snapshot(2, linked_review=True, linked_review_finished=True)
    completed = _review_snapshot(3, reviews_done=10, review_score=0.6)
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_id="work-item-91-finish-review",
                snapshot=initial,
            ),
            _observed(3, SoftwareIncUIScene.GAMEPLAY_PAUSED, snapshot=completed),
        ]
    )
    store = ContractWorkflowStore(tmp_path / "review-finish.sqlite3")

    result = asyncio.run(
        advance_contract(
            _workflow(initial),
            deadline_risk_approval_provider=lambda _approval: True,
            observer_factory=lambda: observer,
            store=store,
        )
    )

    assert result.verified
    assert result.partial
    assert result.workflow is not None
    assert result.gestures_sent == 1
    assert [gesture.target_id for gesture, _ in observer.backend.gestures] == [
        "work-item-91-finish-review"
    ]
    assert [event.event_type for event in store.events(result.workflow.workflow_id)] == [
        "review_finished"
    ]


def _workflow(snapshot: GameSnapshot) -> ContractWorkflow:
    now = datetime.now(UTC)
    return ContractWorkflow(
        workflow_id=uuid4(),
        game_session_id=snapshot.game_session_id,
        save_identity=json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True),
        contract_id="Acme|Utility",
        contract_name="Utility",
        client="Acme",
        team_name="Core",
        minimum_reward=Decimal("1000"),
        minimum_cash_reserve=Decimal("0"),
        reward=Decimal("5000"),
        maximum_penalty=Decimal("1000"),
        deadline="March",
        status=ContractWorkflowStatus.ACTIVE,
        observed_stage=ContractStage.ALPHA,
        work_item_id="42",
        plan_fingerprint="b" * 64,
        accepted_at=now,
        last_bridge_sequence=1,
        created_at=now,
        updated_at=now,
    )


def _design_snapshot(sequence: int, *, promoted: bool = False) -> GameSnapshot:
    snapshot = _review_snapshot(sequence, progress=0.75)
    surfaces: list[ObservationSurface] = []
    for surface in snapshot.surfaces:
        if surface.coverage.surface != "work_items":
            surfaces.append(surface)
            continue
        entities: list[ObservedEntity] = []
        for entity in surface.entities:
            if entity.entity_id != "42":
                entities.append(entity)
                continue
            entities.append(
                entity.model_copy(
                    update={
                        "values": {
                            **entity.values,
                            "minimum_progress": 0.2,
                            "stage": "Alpha" if promoted else "Designing\n1 month left",
                            "work_type": "Software Alpha" if promoted else "Design",
                        }
                    }
                )
            )
        surfaces.append(surface.model_copy(update={"entities": tuple(entities)}))
    return snapshot.model_copy(update={"surfaces": tuple(surfaces)})


def test_promote_opens_exact_work_item_card_before_irreversible_action(
    tmp_path: Path,
) -> None:
    initial = _design_snapshot(2)
    refreshed = _design_snapshot(3)
    opened = _design_snapshot(4)
    promoted = _design_snapshot(5, promoted=True)
    workflow = _workflow(initial).model_copy(update={"observed_stage": ContractStage.DESIGN})
    observer = _Observer(
        [
            _observed(2, SoftwareIncUIScene.GAMEPLAY_PAUSED, snapshot=initial),
            _observed(
                3,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_id="work-item-42-open",
                snapshot=refreshed,
            ),
            _observed(
                4,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_id="work-item-42-promote",
                snapshot=opened,
            ),
            _observed(5, SoftwareIncUIScene.GAMEPLAY_PAUSED, snapshot=promoted),
        ]
    )

    result = asyncio.run(
        promote_contract(
            workflow,
            approval_provider=lambda _approval: True,
            observer_factory=lambda: observer,
            store=ContractWorkflowStore(tmp_path / "promote.sqlite3"),
        )
    )

    assert result.verified
    assert result.gestures_sent == 2
    assert result.workflow is not None
    assert result.workflow.observed_stage is ContractStage.ALPHA
    assert [gesture.target_id for gesture, _ in observer.backend.gestures] == [
        "work-item-42-open",
        "work-item-42-promote",
    ]


def test_promote_uses_exact_peer_review_result_action(tmp_path: Path) -> None:
    initial = _review_snapshot(2, progress=0.75, reviews_done=1, review_score=0.6)
    refreshed = _review_snapshot(3, progress=0.75, reviews_done=1, review_score=0.6)
    beta = _review_snapshot(4, progress=0.75, reviews_done=1, review_score=0.6)
    surfaces: list[ObservationSurface] = []
    for surface in beta.surfaces:
        if surface.coverage.surface != "work_items":
            surfaces.append(surface)
            continue
        entities = tuple(
            entity.model_copy(
                update={
                    "values": {
                        **entity.values,
                        "in_beta": True,
                        "stage": "Beta",
                    }
                }
            )
            if entity.entity_id == "42"
            else entity
            for entity in surface.entities
        )
        surfaces.append(surface.model_copy(update={"entities": entities}))
    beta = beta.model_copy(update={"surfaces": tuple(surfaces)})
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.CONTRACT_REVIEW_RESULT,
                target_id="review_result_promote",
                snapshot=initial,
            ),
            _observed(
                3,
                SoftwareIncUIScene.CONTRACT_REVIEW_RESULT,
                target_id="review_result_promote",
                snapshot=refreshed,
            ),
            _observed(4, SoftwareIncUIScene.GAMEPLAY_PAUSED, snapshot=beta),
        ]
    )

    result = asyncio.run(
        promote_contract(
            _workflow(initial),
            approval_provider=lambda _approval: True,
            observer_factory=lambda: observer,
            store=ContractWorkflowStore(tmp_path / "promote-review-result.sqlite3"),
        )
    )

    assert result.verified
    assert result.workflow is not None
    assert result.gestures_sent == 1
    assert result.workflow is not None
    assert result.workflow.observed_stage is ContractStage.BETA
    assert [gesture.target_id for gesture, _ in observer.backend.gestures] == [
        "review_result_promote"
    ]


def test_review_binds_visible_cost_and_verifies_linked_work(tmp_path: Path) -> None:
    initial = _review_snapshot(2)
    setup = _review_snapshot(3, review_setup=True)
    refreshed_setup = _review_snapshot(4, review_setup=True)
    completed = _review_snapshot(5, linked_review=True)
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_id="work-item-42-review",
                snapshot=initial,
            ),
            _observed(
                3,
                SoftwareIncUIScene.CONTRACT_REVIEW_SETUP,
                target_id="commit_contract_review",
                snapshot=setup,
            ),
            _observed(
                4,
                SoftwareIncUIScene.CONTRACT_REVIEW_SETUP,
                target_id="commit_contract_review",
                snapshot=refreshed_setup,
            ),
            _observed(5, SoftwareIncUIScene.GAMEPLAY_PAUSED, snapshot=completed),
        ]
    )
    approvals: list[ContractApproval] = []

    store = ContractWorkflowStore(tmp_path / "contracts.sqlite3")
    result = asyncio.run(
        review_contract(
            _workflow(initial),
            approval_provider=lambda approval: approvals.append(approval) is None,
            observer_factory=lambda: observer,
            store=store,
        )
    )

    assert result.verified
    assert result.gestures_sent == 2
    assert result.workflow is not None
    assert len(approvals) == 1
    assert approvals[0].one_time_cost == Decimal("1250.00")
    assert approvals[0].configuration == "mode=client, review_count=5"
    assert [event.event_type for event in store.events(result.workflow.workflow_id)] == [
        "review_setup_opened",
        "review_started",
    ]
    assert [gesture.target_id for gesture, _ in observer.backend.gestures] == [
        "work-item-42-review",
        "commit_contract_review",
    ]


def test_review_cost_accepts_verified_count_times_unit_formula() -> None:
    snapshot = _review_snapshot(3, review_setup=True)
    surfaces: list[ObservationSurface] = []
    for surface in snapshot.surfaces:
        if surface.coverage.surface != "contract_ui":
            surfaces.append(surface)
            continue
        state = surface.entities[0]
        surfaces.append(
            surface.model_copy(
                update={
                    "entities": (
                        state.model_copy(
                            update={
                                "values": {
                                    **state.values,
                                    "review_cost_text": "Cost: 10 x $0 = $0",
                                }
                            }
                        ),
                    )
                }
            )
        )

    assert _review_cost(snapshot.model_copy(update={"surfaces": tuple(surfaces)})) == Decimal(
        "0.00"
    )


def test_review_resumes_an_already_observed_setup_without_reopening(tmp_path: Path) -> None:
    setup = _review_snapshot(2, review_setup=True)
    refreshed_setup = _review_snapshot(3, review_setup=True)
    completed = _review_snapshot(4, linked_review=True)
    observer = _Observer(
        [
            _observed(2, SoftwareIncUIScene.CONTRACT_REVIEW_SETUP, snapshot=setup),
            _observed(
                3,
                SoftwareIncUIScene.CONTRACT_REVIEW_SETUP,
                target_id="commit_contract_review",
                snapshot=refreshed_setup,
            ),
            _observed(4, SoftwareIncUIScene.GAMEPLAY_PAUSED, snapshot=completed),
        ]
    )
    store = ContractWorkflowStore(tmp_path / "review-resume.sqlite3")

    result = asyncio.run(
        review_contract(
            _workflow(setup),
            approval_provider=lambda _approval: True,
            observer_factory=lambda: observer,
            store=store,
        )
    )

    assert result.verified
    assert result.workflow is not None
    assert result.gestures_sent == 1
    assert [gesture.target_id for gesture, _ in observer.backend.gestures] == [
        "commit_contract_review"
    ]
    assert [event.event_type for event in store.events(result.workflow.workflow_id)] == [
        "review_setup_resumed",
        "review_started",
    ]


def _accept_snapshot(
    sequence: int,
    *,
    selected: str = "0,1",
    design_teams: str = "Core|Other",
    development_teams: str = "Core",
) -> GameSnapshot:
    base = _snapshot(sequence, market=True)
    state = ObservedEntity(
        entity_type="contract_ui_state",
        entity_id="current",
        values={
            "design_teams": design_teams,
            "development_teams": development_teams,
            "selected_available_indices": selected,
            "scene": "contract_browser",
        },
    )
    return base.model_copy(
        update={
            "surfaces": (
                *base.surfaces,
                ObservationSurface(
                    coverage=FieldCoverage(
                        surface="contract_ui",
                        status=CoverageStatus.OBSERVED_COMPLETE,
                        fields=(),
                    ),
                    entities=(state,),
                ),
                ObservationSurface(
                    coverage=FieldCoverage(
                        surface="work_items",
                        status=CoverageStatus.OBSERVED_COMPLETE,
                        fields=(),
                    ),
                    entities=(),
                ),
            )
        }
    )


def _recommendation(snapshot: GameSnapshot) -> ContractRecommendation:
    contract = available_contracts(snapshot)[0]
    team = TeamContractAssessment(
        team_id="Core",
        team_name="Core",
        employee_count=2,
        required_roles=("Designer", "Programmer"),
        observed_roles=("Designer", "Programmer"),
        missing_roles=(),
        active_work_items=(),
        current_workspace_capacity=2,
        required_workspace_capacity=2,
        conservative_required_days=Decimal("20"),
        deadline_buffer_days=Decimal("20"),
        suitable=True,
        reasons=(),
    )
    candidate = ContractCandidate(
        contract=contract,
        team=team,
        observed_cash=Decimal("100000"),
        worst_case_cash_after_penalty=Decimal("99000"),
        minimum_reward=Decimal("1000"),
        minimum_cash_reserve=Decimal("0"),
        eligible=True,
        reasons=(),
    )
    now = datetime.now(UTC)
    return ContractRecommendation(
        recommendation_id="contract-recommendation:" + "a" * 24,
        game_session_id=snapshot.game_session_id,
        save_identity=json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True),
        source_bridge_sequence=snapshot.bridge_sequence,
        capability_fingerprint="a" * 64,
        recommended=candidate,
        alternatives=(),
        rejected_count=0,
        rejection_reasons=(),
        material_unknowns=(),
        created_at=now,
        expires_at=now + timedelta(minutes=3),
    )


def test_accept_dry_run_replaces_unapproved_multiselection(tmp_path: Path) -> None:
    snapshot = _accept_snapshot(2)
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.CONTRACT_BROWSER,
                target_id="contract_row_0",
                snapshot=snapshot,
            )
        ]
    )

    result = asyncio.run(
        accept_recommended_contract(
            _recommendation(snapshot),
            approval_provider=None,
            dry_run=True,
            observer_factory=lambda: observer,
            store=ContractWorkflowStore(tmp_path / "accept.sqlite3"),
        )
    )

    assert result.gestures_sent == 0
    assert result.partial
    assert "select only exact contract row 0" in result.message
    assert observer.backend.gestures == []


def test_acceptance_does_not_retry_an_unchanged_contract_row(tmp_path: Path) -> None:
    initial = _accept_snapshot(2, selected="", design_teams="Core", development_teams="Core")
    unchanged = _accept_snapshot(3, selected="", design_teams="Core", development_teams="Core")
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.CONTRACT_BROWSER,
                target_id="contract_row_0",
                snapshot=initial,
            ),
            _observed(3, SoftwareIncUIScene.CONTRACT_BROWSER, snapshot=unchanged),
        ]
    )

    with pytest.raises(SoftwareIncUIVerificationError, match="will not be retried"):
        asyncio.run(
            accept_recommended_contract(
                _recommendation(initial),
                approval_provider=lambda _approval: True,
                observer_factory=lambda: observer,
                store=ContractWorkflowStore(tmp_path / "unchanged-row.sqlite3"),
            )
        )

    assert [gesture.target_id for gesture, _ in observer.backend.gestures] == ["contract_row_0"]


def test_acceptance_uses_fresh_post_approval_target(tmp_path: Path) -> None:
    configured = _accept_snapshot(
        2,
        selected="0",
        design_teams="Core",
        development_teams="Core",
    )
    refreshed = _accept_snapshot(
        3,
        selected="0",
        design_teams="Core",
        development_teams="Core",
    )
    accepted = _review_snapshot(4)
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.CONTRACT_BROWSER,
                target_id="commit_contract",
                snapshot=configured,
            ),
            _observed(
                3,
                SoftwareIncUIScene.CONTRACT_BROWSER,
                target_id="commit_contract",
                snapshot=refreshed,
            ),
            _observed(
                4,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                snapshot=accepted,
            ),
        ]
    )

    result = asyncio.run(
        accept_recommended_contract(
            _recommendation(configured),
            approval_provider=lambda _approval: True,
            observer_factory=lambda: observer,
            store=ContractWorkflowStore(tmp_path / "fresh-accept.sqlite3"),
        )
    )

    assert result.verified
    assert result.workflow is not None
    assert result.workflow.work_item_id == "42"
    assert len(observer.backend.gestures) == 1
    assert (
        observer.backend.gestures[0][0].expected_frame_id == hashlib.sha256(b"frame:3").hexdigest()
    )


def _release_snapshot(sequence: int, *, completed: bool) -> GameSnapshot:
    base = _review_snapshot(sequence)
    surfaces = [
        surface
        for surface in base.surfaces
        if surface.coverage.surface not in {"company", "contract_results", "finances", "work_items"}
    ]
    work_items = (
        ()
        if completed
        else next(
            surface.entities
            for surface in base.surfaces
            if surface.coverage.surface == "work_items"
        )
    )
    result_entities = (
        (
            ObservedEntity(
                entity_type="contract_result",
                entity_id="Acme|Utility:0",
                values={
                    "client": "Acme",
                    "final_result": 5500.0,
                    "income": 5000.0,
                    "late_penalty": 0.0,
                    "name": "Utility",
                    "reputation_change": 0.2,
                    "status": "Success",
                },
            ),
        )
        if completed
        else ()
    )
    surfaces.extend(
        (
            ObservationSurface(
                coverage=FieldCoverage(
                    surface="company",
                    status=CoverageStatus.OBSERVED_COMPLETE,
                    fields=(),
                ),
                entities=(
                    ObservedEntity(
                        entity_type="company",
                        entity_id="company",
                        values={"business_reputation": 1.2 if completed else 1.0},
                    ),
                ),
            ),
            ObservationSurface(
                coverage=FieldCoverage(
                    surface="contract_results",
                    status=CoverageStatus.OBSERVED_COMPLETE,
                    fields=(),
                ),
                entities=result_entities,
            ),
            ObservationSurface(
                coverage=FieldCoverage(
                    surface="finances",
                    status=CoverageStatus.OBSERVED_PARTIAL,
                    fields=(),
                ),
                entities=(
                    ObservedEntity(
                        entity_type="company_finances",
                        entity_id="company",
                        values={"cash": 105000.0 if completed else 100000.0},
                    ),
                ),
            ),
            ObservationSurface(
                coverage=FieldCoverage(
                    surface="work_items",
                    status=CoverageStatus.OBSERVED_COMPLETE,
                    fields=(),
                ),
                entities=work_items,
            ),
        )
    )
    return base.model_copy(
        update={"surfaces": tuple(sorted(surfaces, key=lambda surface: surface.coverage.surface))}
    )


def test_release_requires_approval_and_verifies_exact_financial_result(tmp_path: Path) -> None:
    before = _release_snapshot(2, completed=False)
    refreshed = _release_snapshot(3, completed=False)
    after = _release_snapshot(4, completed=True)
    observer = _Observer(
        [
            _observed(
                2,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_id="work-item-42-release",
                snapshot=before,
            ),
            _observed(
                3,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                target_id="work-item-42-release",
                snapshot=refreshed,
            ),
            _observed(4, SoftwareIncUIScene.GAMEPLAY_PAUSED, snapshot=after),
        ]
    )
    store = ContractWorkflowStore(tmp_path / "release.sqlite3")

    result = asyncio.run(
        release_contract(
            _workflow(before),
            approval_provider=lambda _approval: True,
            observer_factory=lambda: observer,
            store=store,
        )
    )

    assert result.verified
    assert result.workflow is not None
    assert result.workflow.status is ContractWorkflowStatus.COMPLETED
    assert "payout=$5,000.00" in result.message
    assert [event.event_type for event in store.events(result.workflow.workflow_id)] == [
        "release_completed"
    ]


def test_release_reconciles_completed_result_without_duplicate_input(tmp_path: Path) -> None:
    before = _release_snapshot(1, completed=False)
    completed = _release_snapshot(2, completed=True)
    observer = _Observer([_observed(2, SoftwareIncUIScene.GAMEPLAY_PAUSED, snapshot=completed)])
    store = ContractWorkflowStore(tmp_path / "release-reconcile.sqlite3")

    result = asyncio.run(
        release_contract(
            _workflow(before),
            approval_provider=None,
            observer_factory=lambda: observer,
            store=store,
        )
    )

    assert result.verified
    assert result.gestures_sent == 0
    assert result.workflow is not None
    assert result.workflow.status is ContractWorkflowStatus.COMPLETED
    assert result.workflow.observed_stage is ContractStage.COMPLETED
    assert "without retrying release" in result.message
    assert observer.backend.gestures == []
    assert [event.event_type for event in store.events(result.workflow.workflow_id)] == [
        "release_reconciled"
    ]
