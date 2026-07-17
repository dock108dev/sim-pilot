"""Typed fixtures for decision-provider tests."""

from datetime import UTC, datetime
from decimal import Decimal

from sim_pilot.adapters.reference.adapter import ACTION_DEFINITIONS
from sim_pilot.domain import Observation
from sim_pilot.runtime.decision_context import DecisionContext, DecisionContextProjector
from sim_pilot.runtime.models import (
    EvaluationStatus,
    RuntimeEvaluation,
    RuntimeEvent,
    RuntimeSafeguardState,
)
from tests.runtime.helpers import make_task


def make_context(
    *,
    state: dict[str, object] | None = None,
    events: tuple[RuntimeEvent, ...] = (),
    max_recent_events: int = 20,
    max_serialized_bytes: int = 65_536,
    complete: bool = False,
) -> DecisionContext:
    task = make_task().model_copy(update={"total_spend": Decimal("100")})
    observation = Observation(
        sequence=2,
        timestamp=datetime.now(UTC),
        tick=1,
        summary="Reference state for a decision.",
        state=state
        or {
            "cash": 500_000.0,
            "debt": 0.0,
            "population": 500,
            "housing": 600,
            "power_capacity": 700,
            "power_usage": 500,
            "infrastructure": 90.0,
            "maintenance_level": 0.5,
            "active_projects": [],
            "paused": False,
            "failed": False,
        },
    )
    return DecisionContextProjector(
        max_recent_events=max_recent_events,
        max_serialized_bytes=max_serialized_bytes,
    ).project(
        task=task,
        observation=observation,
        available_actions=list(ACTION_DEFINITIONS),
        events=events,
        runtime_state=RuntimeSafeguardState(),
        progress=RuntimeEvaluation(
            current_status=(EvaluationStatus.COMPLETED if complete else EvaluationStatus.RUNNING),
            complete=complete,
            progress_summary="Objective complete." if complete else "Objective is in progress.",
        ),
    )
