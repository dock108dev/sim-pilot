"""Deterministic reconciliation for the standalone reference simulation."""

from collections.abc import Mapping

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.runtime.action_attempts import (
    ActionAttempt,
    ActionAttemptStatus,
    ReconciliationClassification,
)
from sim_pilot.runtime.recovery import ReconciliationReport


async def reconcile_reference_action(
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
