"""Visible UI start, bounded progression, and idempotence for Prompt 6B."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
from sim_pilot.game_bridge import CoverageStatus, FieldCoverage, ObservationSurface, ObservedEntity
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError
from sim_pilot.software_inc.training import TrainingWorkflowStatus, recommend_training
from sim_pilot.software_inc.training.operator import advance_training, start_training
from sim_pilot.software_inc.training.store import TrainingWorkflowStore
from sim_pilot.software_inc.training.workflow import (
    create_training_workflow,
    resolve_training_approval,
    synchronize_training,
)
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    VisualTarget,
)
from sim_pilot.software_inc.ui.observer import ObservedSoftwareIncUI
from tests.software_inc.test_training import _snapshot  # pyright: ignore[reportPrivateUsage]


class _Backend:
    def __init__(self) -> None:
        self.gestures: list[InputGesture] = []

    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> InputExecutionResult:
        assert gesture.expected_frame_id == frame.frame_id
        self.gestures.append(gesture)
        return InputExecutionResult(gesture=gesture, sent_at=datetime.now(UTC))


class _Observer:
    def __init__(
        self,
        observations: list[ObservedSoftwareIncUI],
        *,
        foreground_error: Exception | None = None,
    ) -> None:
        self._observations = iter(observations)
        self.backend = _Backend()
        self.foreground_calls = 0
        self.foreground_error = foreground_error

    async def observe(self) -> ObservedSoftwareIncUI:
        return next(self._observations)

    async def keep_game_foreground(self) -> None:
        self.foreground_calls += 1
        if self.foreground_error is not None:
            raise self.foreground_error


def _ui_snapshot(
    sequence: int,
    *,
    scene: SoftwareIncUIScene,
    selected: str = "",
    role: str = "",
    specialization: str = "",
    cost: float = 0,
    course: str = "",
    level: int = 0,
    cash: float = 100_000,
    paused: bool = True,
):
    snapshot = _snapshot(
        sequence,
        cash=cash,
        founder_course=course,
        founder_level=level,
    )
    state = ObservedEntity(
        entity_type="education_ui_state",
        entity_id="current",
        values={
            "duration_months": 1,
            "role_items": "Lead|Programmer|Designer|Artist|Service",
            "scene": (
                "education"
                if scene is SoftwareIncUIScene.EDUCATION
                else "employee_management"
                if scene is SoftwareIncUIScene.EMPLOYEE_MANAGEMENT
                else "gameplay"
            ),
            "selected_cost": cost,
            "selected_employees": selected,
            "selected_role": role,
            "selected_specialization": specialization,
            "specialization_items": "System|2D|3D",
            "start_label": "Educate",
        },
    )
    return snapshot.model_copy(
        update={
            "game_state": {
                **snapshot.game_state,
                "force_pause": paused,
                "simulation_speed": "0" if paused else "1",
            },
            "surfaces": tuple(
                sorted(
                    (
                        *snapshot.surfaces,
                        ObservationSurface(
                            coverage=FieldCoverage(
                                surface="education_ui",
                                status=CoverageStatus.OBSERVED_COMPLETE,
                                fields=(),
                            ),
                            entities=(state,),
                        ),
                    ),
                    key=lambda surface: surface.coverage.surface,
                )
            ),
        }
    )


def _observed(
    sequence: int,
    scene: SoftwareIncUIScene,
    target_ids: tuple[str, ...],
    *,
    selected: str = "",
    role: str = "",
    specialization: str = "",
    cost: float = 0,
    course: str = "",
    level: int = 0,
    cash: float = 100_000,
    paused: bool = True,
) -> ObservedSoftwareIncUI:
    image = Image.new("RGB", (800, 600), (80, 90, 100))
    digest = hashlib.sha256(f"training:{sequence}".encode()).hexdigest()
    bounds = WindowBounds(x=0, y=0, width=800, height=600)
    frame = DesktopFrame(
        frame_id=digest,
        capture_sequence=sequence,
        captured_at=datetime.now(UTC),
        process_id=77,
        window_id="window",
        window_title="Software Inc",
        window_bounds=bounds,
        window_frontmost=True,
        pixel_width=800,
        pixel_height=600,
        display_scale=1,
        sha256=digest,
        platform="macos",
    )
    snapshot = _ui_snapshot(
        sequence,
        scene=scene,
        selected=selected,
        role=role,
        specialization=specialization,
        cost=cost,
        course=course,
        level=level,
        cash=cash,
        paused=paused,
    )
    targets = tuple(
        VisualTarget(
            target_id=target_id,
            source_frame_id=digest,
            point=ScreenPoint(x=100 + index * 30, y=100),
            region=WindowBounds(x=90 + index * 30, y=90, width=20, height=20),
            scene=scene,
            projection_id="a" * 64,
            confidence=1,
            evidence=("fixture",),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        for index, target_id in enumerate(target_ids)
    )
    observation = SoftwareIncUIObservation(
        semantic_before=snapshot.model_copy(update={"bridge_sequence": sequence - 1}),
        semantic_after=snapshot,
        frame=frame,
        scene=scene,
        modal_state=ModalState.NONE,
        projection_id="a" * 64,
        targets=targets,
        synchronization_started_at=datetime.now(UTC),
        synchronization_completed_at=datetime.now(UTC),
        synchronization_duration_seconds=0,
        semantic_capture_skew_seconds=0,
    )
    return ObservedSoftwareIncUI(observation, CapturedDesktopFrame(frame, image))


def test_start_and_complete_exact_education_through_visible_ui(tmp_path: Path) -> None:
    recommendation = recommend_training(
        _snapshot(10), team_name="Core", minimum_cash_reserve=Decimal("50000")
    )
    start_observer = _Observer(
        [
            _observed(11, SoftwareIncUIScene.GAMEPLAY_PAUSED, ("open_employees",)),
            _observed(
                12,
                SoftwareIncUIScene.EMPLOYEE_MANAGEMENT,
                ("employee_row_100",),
            ),
            _observed(
                13,
                SoftwareIncUIScene.EMPLOYEE_MANAGEMENT,
                ("open_education",),
                selected="100",
            ),
            _observed(
                14,
                SoftwareIncUIScene.EDUCATION,
                ("commit_education",),
                selected="100",
                role="Designer",
                specialization="System",
                cost=600,
            ),
            _observed(
                15,
                SoftwareIncUIScene.EDUCATION,
                ("commit_education",),
                selected="100",
                role="Designer",
                specialization="System",
                cost=600,
            ),
            _observed(
                16,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                (),
                course="Designer:System",
                cash=99_400,
            ),
        ]
    )
    store = TrainingWorkflowStore(tmp_path / "training.sqlite3")
    started = asyncio.run(
        start_training(
            recommendation,
            approval_provider=lambda _approval: True,
            observer_factory=lambda: start_observer,
            store=store,
        )
    )
    assert started.verified
    assert started.gestures_sent == 4
    assert started.workflow is not None
    assert started.workflow.status.value == "active"
    assert [gesture.target_id for gesture in start_observer.backend.gestures] == [
        "open_employees",
        "employee_row_100",
        "open_education",
        "commit_education",
    ]

    advance_observer = _Observer(
        [
            _observed(
                17,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                ("resume_button",),
                course="Designer:System",
                cash=99_400,
            ),
            _observed(
                18,
                SoftwareIncUIScene.GAMEPLAY_RUNNING,
                ("pause_button",),
                course="Designer:System",
                cash=99_400,
                paused=False,
            ),
            _observed(
                19,
                SoftwareIncUIScene.GAMEPLAY_RUNNING,
                ("pause_button",),
                level=1,
                cash=99_400,
                paused=False,
            ),
            _observed(
                20,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                (),
                level=1,
                cash=99_400,
            ),
        ]
    )
    completed = asyncio.run(
        advance_training(
            started.workflow,
            run_seconds=0.001,
            observer_factory=lambda: advance_observer,
            store=store,
        )
    )
    assert completed.verified and completed.partial
    assert completed.workflow is not None
    assert completed.workflow.status.value == "waiting_for_approval"
    assert completed.workflow.current_level == 1
    assert advance_observer.foreground_calls == 1
    assert [gesture.target_id for gesture in advance_observer.backend.gestures] == [
        "resume_button",
        "pause_button",
    ]


def test_advance_guarantees_pause_when_interval_is_interrupted(tmp_path: Path) -> None:
    recommendation = recommend_training(
        _snapshot(10), team_name="Core", minimum_cash_reserve=Decimal("50000")
    )
    assert recommendation.recommended is not None
    workflow = create_training_workflow(_snapshot(10), recommendation.recommended).model_copy(
        update={"status": TrainingWorkflowStatus.ACTIVE}
    )
    observer = _Observer(
        [
            _observed(
                11,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                ("resume_button",),
                course="Designer:System",
            ),
            _observed(
                12,
                SoftwareIncUIScene.GAMEPLAY_RUNNING,
                ("pause_button",),
                course="Designer:System",
                paused=False,
            ),
            _observed(
                13,
                SoftwareIncUIScene.GAMEPLAY_RUNNING,
                ("pause_button",),
                course="Designer:System",
                paused=False,
            ),
            _observed(
                14,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                (),
                course="Designer:System",
            ),
        ],
        foreground_error=RuntimeError("foreground interrupted"),
    )

    with pytest.raises(RuntimeError, match="foreground interrupted"):
        asyncio.run(
            advance_training(
                workflow,
                run_seconds=0.001,
                observer_factory=lambda: observer,
                store=TrainingWorkflowStore(tmp_path / "training.sqlite3"),
            )
        )

    assert [gesture.target_id for gesture in observer.backend.gestures] == [
        "resume_button",
        "pause_button",
    ]


def test_next_course_requires_fresh_approval_and_current_price(tmp_path: Path) -> None:
    recommendation = recommend_training(
        _snapshot(10), team_name="Core", minimum_cash_reserve=Decimal("50000")
    )
    assert recommendation.recommended is not None
    first = resolve_training_approval(
        create_training_workflow(_snapshot(10), recommendation.recommended), approved=True
    ).model_copy(update={"actual_direct_cost": Decimal("600")})
    active = synchronize_training(
        first, _snapshot(11, cash=99_400, founder_course="Designer:System")
    )
    stage_two = synchronize_training(active, _snapshot(12, cash=99_400, founder_level=1))
    observer = _Observer(
        [
            _observed(
                13,
                SoftwareIncUIScene.EDUCATION,
                ("commit_education",),
                selected="100",
                role="Designer",
                specialization="System",
                cost=2_000,
                level=1,
                cash=99_400,
            ),
            _observed(
                14,
                SoftwareIncUIScene.EDUCATION,
                ("commit_education",),
                selected="100",
                role="Designer",
                specialization="System",
                cost=2_000,
                level=1,
                cash=99_400,
            ),
            _observed(
                15,
                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                (),
                course="Designer:System",
                level=1,
                cash=97_400,
            ),
        ]
    )
    result = asyncio.run(
        start_training(
            None,
            existing_workflow=stage_two,
            approval_provider=lambda approval: approval.stage_number == 2,
            observer_factory=lambda: observer,
            store=TrainingWorkflowStore(tmp_path / "training.sqlite3"),
        )
    )
    assert result.workflow is not None
    assert result.workflow.status is TrainingWorkflowStatus.ACTIVE
    assert result.workflow.actual_direct_cost == Decimal("2600")
    assert [gesture.target_id for gesture in observer.backend.gestures] == ["commit_education"]


def test_no_candidate_rejects_before_ui_observation() -> None:
    recommendation = recommend_training(
        _snapshot(10, founder_level=3),
        team_name="Core",
        minimum_cash_reserve=Decimal("50000"),
    )
    assert recommendation.recommended is None

    with pytest.raises(SoftwareIncUIValidationError, match="no eligible employee"):
        asyncio.run(
            start_training(
                recommendation,
                approval_provider=None,
                observer_factory=lambda: pytest.fail("UI observer must not be constructed"),
            )
        )
