"""Bounded deterministic decision-context projection."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sim_pilot.domain import Action, ExecutionResult, Observation
from sim_pilot.runtime.decision_context import DecisionContextProjector
from sim_pilot.runtime.decision_errors import DecisionContextTooLargeError
from sim_pilot.runtime.models import (
    EvaluationStatus,
    RuntimeEvaluation,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeSafeguardState,
    VerificationResult,
)
from tests.decision_provider.helpers import make_context
from tests.runtime.helpers import make_task


def _event(sequence: int, event_type: RuntimeEventType, payload: dict[str, object]) -> RuntimeEvent:
    return RuntimeEvent(
        task_id=make_task().id,
        sequence=sequence,
        event_type=event_type,
        timestamp=datetime.now(UTC),
        payload=payload,  # type: ignore[arg-type]
    )


def test_context_serialization_is_stable_and_contains_required_state() -> None:
    first = make_context()
    second = first.model_copy()
    assert first.canonical_json() == second.canonical_json()
    assert first.task_id == make_task().id
    assert first.specification == make_task().specification
    assert first.accumulated_spend == 100
    assert len(first.available_actions) == 9
    assert first.progress.complete is False


def test_projection_summarizes_previous_observation_execution_and_restrictions() -> None:
    action = Action(
        type="advance_time",
        parameters={"ticks": 1},
        expected_effect="Advance one tick.",
    )
    previous = Observation(
        sequence=1,
        timestamp=datetime.now(UTC),
        tick=0,
        summary="Previous.",
        state={"cash": 500_000.0},
    )
    events = (
        _event(1, RuntimeEventType.OBSERVATION_RECORDED, previous.model_dump(mode="json")),
        _event(
            2,
            RuntimeEventType.ACTION_PREPARED,
            {"action": action.model_dump(mode="json"), "action_id": str(uuid4())},
        ),
        _event(
            3,
            RuntimeEventType.ACTION_EXECUTED,
            ExecutionResult(
                success=True, state_changed=True, cost=0, message="Advanced."
            ).model_dump(mode="json"),
        ),
        _event(
            4,
            RuntimeEventType.VERIFICATION_RECORDED,
            VerificationResult(verified=True).model_dump(mode="json"),
        ),
        _event(5, RuntimeEventType.ACTION_REJECTED, {"reason": "reserve violation"}),
    )
    task = make_task()
    current = make_context().observation
    context = DecisionContextProjector().project(
        task=task,
        observation=current,
        available_actions=list(make_context().available_actions),
        events=events,
        runtime_state=RuntimeSafeguardState(rejected_action_count=1),
        progress=RuntimeEvaluation(
            current_status=EvaluationStatus.RUNNING,
            complete=False,
            progress_summary="Running.",
        ),
    )
    assert context.previous_observation == previous
    assert context.previous_execution is not None
    assert context.previous_execution.action == action
    assert context.previous_execution.result is not None
    assert context.previous_execution.verification is not None
    assert context.pending_restrictions.rejected_actions == ("reserve violation",)


def test_projection_truncates_oldest_events_and_rejects_oversized_base_context() -> None:
    events = tuple(
        _event(
            sequence,
            RuntimeEventType.ACTION_REJECTED,
            {"reason": f"rejected-{sequence}"},
        )
        for sequence in range(1, 8)
    )
    context = make_context(events=events, max_recent_events=3)
    assert [event.sequence for event in context.recent_events] == [5, 6, 7]
    base_size = len(make_context().canonical_json().encode())
    byte_limited = make_context(
        events=events,
        max_recent_events=20,
        max_serialized_bytes=base_size + 250,
    )
    assert len(byte_limited.recent_events) < len(events)
    with pytest.raises(DecisionContextTooLargeError):
        make_context(max_serialized_bytes=100)
