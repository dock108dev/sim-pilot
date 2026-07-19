"""Explicit adapter-type reconciliation registration and dispatch."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.domain import Action
from sim_pilot.reconciliation import default_reconciliation_dispatcher
from sim_pilot.runtime.action_attempts import ActionAttempt, ActionAttemptStatus, action_fingerprint
from sim_pilot.runtime.recovery import (
    AdapterReconciliationMismatchError,
    ReconciliationDispatcher,
    ReconciliationReport,
    UnsupportedAdapterReconciliationError,
)


def _snapshot(adapter_type: str) -> AdapterSnapshot:
    return AdapterSnapshot(
        adapter_type=adapter_type,
        simulation_schema_version=1,
        observation_sequence=1,
        seed="0",
        state={"schema_version": 1, "tick": 0},
    )


def _attempt() -> ActionAttempt:
    action = Action(type="pause", expected_effect="Pause.")
    now = datetime.now(UTC)
    return ActionAttempt(
        task_id=UUID(int=1),
        runtime_sequence=1,
        action_id=UUID(int=2),
        action_fingerprint=action_fingerprint(action),
        action=action,
        prior_checkpoint_id=UUID(int=3),
        prior_observation_fingerprint="prior",
        expected_effect=action.expected_effect,
        estimated_cost=0,
        status=ActionAttemptStatus.EXECUTION_STARTED,
        prepared_at=now,
        updated_at=now,
    )


def test_multiple_adapters_require_explicit_unique_registration() -> None:
    dispatcher = default_reconciliation_dispatcher()
    assert set(dispatcher.adapter_types) == {
        "reference",
        "openttd",
        "sim_pilot.adapters.openttd.adapter.OpenTTDAdapter",
    }

    async def duplicate(
        attempt: ActionAttempt,
        prior: AdapterSnapshot,
        current: AdapterSnapshot | None,
    ) -> ReconciliationReport:
        raise AssertionError((attempt, prior, current))

    with pytest.raises(ValueError, match="already registered"):
        dispatcher.register("reference", duplicate)


def test_unknown_adapter_and_mismatched_fresh_snapshot_fail_closed() -> None:
    attempt = _attempt()
    dispatcher = ReconciliationDispatcher()
    with pytest.raises(UnsupportedAdapterReconciliationError, match="unknown"):
        asyncio.run(dispatcher.reconcile(attempt, _snapshot("unknown"), None))

    dispatcher = default_reconciliation_dispatcher()
    with pytest.raises(AdapterReconciliationMismatchError, match="does not match"):
        asyncio.run(
            dispatcher.reconcile(
                attempt,
                _snapshot("reference"),
                _snapshot("openttd"),
            )
        )


def test_registered_adapter_dispatches_only_to_its_reconciler() -> None:
    calls: list[str] = []

    async def first(
        attempt: ActionAttempt,
        prior: AdapterSnapshot,
        current: AdapterSnapshot | None,
    ) -> ReconciliationReport:
        del attempt, prior, current
        calls.append("first")
        raise RuntimeError("selected")

    async def second(
        attempt: ActionAttempt,
        prior: AdapterSnapshot,
        current: AdapterSnapshot | None,
    ) -> ReconciliationReport:
        del attempt, prior, current
        calls.append("second")
        raise RuntimeError("wrong")

    dispatcher = ReconciliationDispatcher({"first": first, "second": second})
    with pytest.raises(RuntimeError, match="selected"):
        asyncio.run(dispatcher.reconcile(_attempt(), _snapshot("first"), None))
    assert calls == ["first"]
