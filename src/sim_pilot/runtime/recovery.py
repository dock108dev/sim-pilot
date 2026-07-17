"""Deterministic reconciliation for interrupted external action attempts."""

from collections.abc import Mapping
from enum import StrEnum
from typing import cast

from pydantic import ConfigDict

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.domain import ExecutionResult
from sim_pilot.runtime.action_attempts import (
    ActionAttempt,
    ActionAttemptStatus,
    ReconciliationClassification,
)
from sim_pilot.runtime.models import RuntimeModel


class CrashPoint(StrEnum):
    AFTER_PREPARED = "after_prepared"
    BEFORE_EXECUTION = "before_execution"
    AFTER_EXECUTION = "after_execution"
    AFTER_OBSERVATION = "after_observation"
    AFTER_VERIFICATION = "after_verification"
    AFTER_COMMIT = "after_commit"


class ReconciliationReport(RuntimeModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, arbitrary_types_allowed=True
    )

    attempt: ActionAttempt
    classification: ReconciliationClassification
    reason: str
    prior_snapshot: AdapterSnapshot
    current_snapshot: AdapterSnapshot | None = None
    expected_snapshot: AdapterSnapshot | None = None
    expected_result: ExecutionResult | None = None


async def reconcile_reference_action(
    attempt: ActionAttempt,
    prior_snapshot: AdapterSnapshot,
    current_snapshot: AdapterSnapshot | None,
) -> ReconciliationReport:
    """Classify current reference state without executing against the live adapter."""
    if attempt.status is ActionAttemptStatus.PREPARED:
        return ReconciliationReport(
            attempt=attempt,
            classification=ReconciliationClassification.DEFINITELY_NOT_EXECUTED,
            reason="execution boundary was never entered",
            prior_snapshot=prior_snapshot,
            current_snapshot=current_snapshot,
        )
    if current_snapshot is None:
        return ReconciliationReport(
            attempt=attempt,
            classification=ReconciliationClassification.ADAPTER_UNAVAILABLE,
            reason="current adapter state is not independently observable",
            prior_snapshot=prior_snapshot,
        )

    expected_adapter = ReferenceSimulationAdapter.from_snapshot(prior_snapshot)
    await expected_adapter.initialize()
    expected_result = await expected_adapter.execute(attempt.action)
    expected_snapshot = expected_adapter.snapshot()
    await expected_adapter.shutdown()

    if current_snapshot.state == prior_snapshot.state:
        classification = ReconciliationClassification.DEFINITELY_NOT_EXECUTED
        reason = "current state exactly matches the prior checkpoint"
    elif current_snapshot.state == expected_snapshot.state:
        classification = ReconciliationClassification.DEFINITELY_EXECUTED
        reason = "current state exactly matches deterministic action replay"
    elif _effect_signature_matches(
        attempt.action.type,
        prior_snapshot.state,
        expected_snapshot.state,
        current_snapshot.state,
    ):
        classification = ReconciliationClassification.INFERABLE
        reason = "action-specific effect matches, but unrelated state also differs"
    else:
        classification = ReconciliationClassification.AMBIGUOUS
        reason = "current state matches neither the prior nor deterministic expected state"
    return ReconciliationReport(
        attempt=attempt,
        classification=classification,
        reason=reason,
        prior_snapshot=prior_snapshot,
        current_snapshot=current_snapshot,
        expected_snapshot=expected_snapshot,
        expected_result=expected_result,
    )


async def reconcile_action(
    attempt: ActionAttempt,
    prior_snapshot: AdapterSnapshot,
    current_snapshot: AdapterSnapshot | None,
) -> ReconciliationReport:
    """Dispatch reconciliation without importing adapter internals into runtime orchestration."""
    if attempt.action.type == "set_server_name":
        return _reconcile_set_server_name(attempt, prior_snapshot, current_snapshot)
    return await reconcile_reference_action(attempt, prior_snapshot, current_snapshot)


def _reconcile_set_server_name(
    attempt: ActionAttempt,
    prior_snapshot: AdapterSnapshot,
    current_snapshot: AdapterSnapshot | None,
) -> ReconciliationReport:
    if attempt.status is ActionAttemptStatus.PREPARED:
        return ReconciliationReport(
            attempt=attempt,
            classification=ReconciliationClassification.DEFINITELY_NOT_EXECUTED,
            reason="execution boundary was never entered",
            prior_snapshot=prior_snapshot,
            current_snapshot=current_snapshot,
        )
    if current_snapshot is None:
        return ReconciliationReport(
            attempt=attempt,
            classification=ReconciliationClassification.ADAPTER_UNAVAILABLE,
            reason="current OpenTTD state is unavailable",
            prior_snapshot=prior_snapshot,
        )
    requested = attempt.action.parameters.get("name")
    prior_name = _nested_resource(prior_snapshot.state, "server_name")
    current_name = _nested_resource(current_snapshot.state, "server_name")
    if not isinstance(requested, str) or not isinstance(prior_name, str):
        classification = ReconciliationClassification.AMBIGUOUS
        reason = "persisted server-name action or checkpoint is invalid"
        result = None
    elif current_name == requested and prior_name != requested:
        classification = ReconciliationClassification.DEFINITELY_EXECUTED
        reason = "fresh OpenTTD welcome metadata contains the requested server name"
        result = ExecutionResult(
            success=True,
            state_changed=True,
            cost=0.0,
            message="Reconciled from fresh OpenTTD welcome metadata.",
        )
    elif current_name == prior_name:
        classification = ReconciliationClassification.DEFINITELY_NOT_EXECUTED
        reason = "fresh OpenTTD welcome metadata still contains the prior server name"
        result = ExecutionResult(
            success=True,
            state_changed=True,
            cost=0.0,
            message="Expected result if the action is accepted as executed.",
        )
    else:
        classification = ReconciliationClassification.AMBIGUOUS
        reason = "server name matches neither the prior nor requested value"
        result = None
    return ReconciliationReport(
        attempt=attempt,
        classification=classification,
        reason=reason,
        prior_snapshot=prior_snapshot,
        current_snapshot=current_snapshot,
        expected_result=result,
    )


def _nested_resource(state: Mapping[str, object], name: str) -> object:
    resources = state.get("resources")
    return (
        cast("dict[str, object]", resources).get(name)
        if isinstance(resources, dict)
        else state.get(name)
    )


def _effect_signature_matches(
    action_type: str,
    before: Mapping[str, object],
    expected: Mapping[str, object],
    current: Mapping[str, object],
) -> bool:
    keys = {
        "advance_time": ("tick", "cash", "population", "active_projects"),
        "build_housing": ("cash", "active_projects"),
        "build_power": ("cash", "active_projects"),
        "repair": ("cash", "infrastructure"),
        "set_maintenance": ("maintenance_level",),
        "take_loan": ("cash", "debt"),
        "repay_loan": ("cash", "debt"),
        "pause": ("paused",),
        "resume": ("paused",),
    }.get(action_type)
    if keys is None:
        return False
    changed = tuple(key for key in keys if before.get(key) != expected.get(key))
    return bool(changed) and all(current.get(key) == expected.get(key) for key in changed)
