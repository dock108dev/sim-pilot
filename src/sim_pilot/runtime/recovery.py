"""Adapter-neutral dispatch for interrupted external action reconciliation."""

from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum

from pydantic import ConfigDict

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.domain import ExecutionResult
from sim_pilot.runtime.action_attempts import ActionAttempt, ReconciliationClassification
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


type ActionReconciler = Callable[
    [ActionAttempt, AdapterSnapshot, AdapterSnapshot | None],
    Awaitable[ReconciliationReport],
]


class UnsupportedAdapterReconciliationError(ValueError):
    """No reconciler was explicitly registered for a persisted adapter type."""


class AdapterReconciliationMismatchError(ValueError):
    """Fresh state belongs to a different adapter than the persisted checkpoint."""


class ReconciliationDispatcher:
    """Dispatch strictly by persisted adapter type through explicit registrations."""

    def __init__(self, registrations: Mapping[str, ActionReconciler] | None = None) -> None:
        self._registrations: dict[str, ActionReconciler] = {}
        for adapter_type, reconciler in (registrations or {}).items():
            self.register(adapter_type, reconciler)

    @property
    def adapter_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    def register(self, adapter_type: str, reconciler: ActionReconciler) -> None:
        key = adapter_type.strip()
        if not key:
            raise ValueError("reconciliation adapter type must not be empty")
        if key in self._registrations:
            raise ValueError(f"reconciler already registered for adapter type {key!r}")
        self._registrations[key] = reconciler

    async def reconcile(
        self,
        attempt: ActionAttempt,
        prior_snapshot: AdapterSnapshot,
        current_snapshot: AdapterSnapshot | None,
    ) -> ReconciliationReport:
        if (
            current_snapshot is not None
            and current_snapshot.adapter_type != prior_snapshot.adapter_type
        ):
            raise AdapterReconciliationMismatchError(
                "current adapter snapshot type does not match the persisted checkpoint"
            )
        reconciler = self._registrations.get(prior_snapshot.adapter_type)
        if reconciler is None:
            raise UnsupportedAdapterReconciliationError(
                f"no reconciler registered for adapter type {prior_snapshot.adapter_type!r}"
            )
        return await reconciler(attempt, prior_snapshot, current_snapshot)
