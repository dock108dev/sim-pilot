"""Lifecycle, event-store, and scripted-provider unit tests."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from sim_pilot.domain import Decision, DecisionType, Observation, TaskStatus
from sim_pilot.runtime.decisions import (
    ScriptedDecisionExhaustedError,
    ScriptedDecisionProvider,
)
from sim_pilot.runtime.events import InMemoryEventStore
from sim_pilot.runtime.lifecycle import TRANSITIONS, transition
from sim_pilot.runtime.models import RuntimeEvent, RuntimeEventType
from tests.runtime.helpers import make_task


def test_every_documented_transition_is_valid() -> None:
    for source, targets in TRANSITIONS.items():
        for target in targets:
            assert transition(source, target) is target


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.COMPLETED),
        (TaskStatus.COMPLETED, TaskStatus.RUNNING),
        (TaskStatus.BLOCKED, TaskStatus.RUNNING),
        (TaskStatus.FAILED, TaskStatus.CANCELLED),
    ],
)
def test_invalid_transitions_fail(source: TaskStatus, target: TaskStatus) -> None:
    with pytest.raises(ValueError, match="invalid task transition"):
        transition(source, target)


def event(sequence: int) -> RuntimeEvent:
    return RuntimeEvent(
        task_id=UUID("00000000-0000-0000-0000-000000000100"),
        sequence=sequence,
        event_type=RuntimeEventType.TASK_CREATED,
        timestamp=datetime.now(UTC),
    )


def test_event_store_orders_and_returns_latest() -> None:
    store = InMemoryEventStore()
    store.append(event(1))
    store.append(event(2))

    assert [item.sequence for item in store.list_events(event(1).task_id)] == [1, 2]
    latest = store.latest(event(1).task_id)
    assert latest is not None
    assert latest.sequence == 2


@pytest.mark.parametrize("sequence", [1, 3])
def test_event_store_rejects_duplicate_or_out_of_order(sequence: int) -> None:
    store = InMemoryEventStore()
    store.append(event(1))

    with pytest.raises(ValueError, match="expected event sequence 2"):
        store.append(event(sequence))


def test_scripted_provider_returns_one_decision_and_counts_requests() -> None:
    async def scenario() -> None:
        decision = Decision(type=DecisionType.WAIT, reason="Wait once.")
        provider = ScriptedDecisionProvider([decision])
        observation = Observation(
            sequence=1,
            timestamp=datetime.now(UTC),
            tick=0,
            summary="Initial.",
            state={},
        )

        assert await provider.decide(make_task(), observation) == decision
        assert provider.request_count == 1
        with pytest.raises(ScriptedDecisionExhaustedError, match="exhausted"):
            await provider.decide(make_task(), observation)

    asyncio.run(scenario())
