"""State-comparable reconciliation for verified OpenTTD setting actions."""

from collections.abc import Mapping
from typing import cast

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.domain import ExecutionResult
from sim_pilot.runtime.action_attempts import (
    ActionAttempt,
    ActionAttemptStatus,
    ReconciliationClassification,
)
from sim_pilot.runtime.recovery import ReconciliationReport

SUPPORTED_ACTION_RESOURCES = {
    "set_server_name": "server_name",
    "set_company_name": "company_name",
}


async def reconcile_openttd_action(
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

    resource = SUPPORTED_ACTION_RESOURCES.get(attempt.action.type)
    if resource is None:
        return ReconciliationReport(
            attempt=attempt,
            classification=ReconciliationClassification.AMBIGUOUS,
            reason=f"OpenTTD action {attempt.action.type!r} has no registered state comparison",
            prior_snapshot=prior_snapshot,
            current_snapshot=current_snapshot,
        )
    if resource == "company_name" and not _bridge_identity_matches(
        prior_snapshot.state, current_snapshot.state
    ):
        return ReconciliationReport(
            attempt=attempt,
            classification=ReconciliationClassification.AMBIGUOUS,
            reason="GameScript identity or company context changed across the crash boundary",
            prior_snapshot=prior_snapshot,
            current_snapshot=current_snapshot,
        )

    requested = attempt.action.parameters.get("name")
    prior_value = _nested_resource(prior_snapshot.state, resource)
    current_value = _nested_resource(current_snapshot.state, resource)
    if not isinstance(requested, str) or not isinstance(prior_value, str):
        classification = ReconciliationClassification.AMBIGUOUS
        reason = f"persisted {resource.replace('_', '-')} action or checkpoint is invalid"
        result = None
    elif current_value == requested and prior_value != requested:
        classification = ReconciliationClassification.DEFINITELY_EXECUTED
        reason = f"fresh OpenTTD state contains the requested {resource.replace('_', ' ')}"
        result = ExecutionResult(
            success=True,
            state_changed=True,
            cost=0.0,
            message=f"Reconciled {resource} from fresh OpenTTD state.",
        )
    elif current_value == prior_value:
        classification = ReconciliationClassification.DEFINITELY_NOT_EXECUTED
        reason = f"fresh OpenTTD state still contains the prior {resource.replace('_', ' ')}"
        result = ExecutionResult(
            success=True,
            state_changed=True,
            cost=0.0,
            message="Expected result if the action is accepted as executed.",
        )
    else:
        classification = ReconciliationClassification.AMBIGUOUS
        reason = f"{resource.replace('_', ' ')} matches neither the prior nor requested value"
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


def _bridge_identity_matches(
    prior_state: Mapping[str, object], current_state: Mapping[str, object]
) -> bool:
    prior = _bridge_identity(prior_state)
    current = _bridge_identity(current_state)
    return prior is not None and current is not None and prior == current


def _bridge_identity(state: Mapping[str, object]) -> tuple[object, object, object] | None:
    bridge = state.get("bridge")
    if not isinstance(bridge, dict):
        return None
    typed_bridge = cast("dict[str, object]", bridge)
    instance_id = typed_bridge.get("script_instance_id")
    company_id = typed_bridge.get("active_company_context")
    fingerprint = typed_bridge.get("capability_fingerprint")
    if not isinstance(instance_id, str):
        return None
    return instance_id, company_id, fingerprint
