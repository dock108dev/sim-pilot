"""Deterministic runtime orchestration components with cycle-safe lazy exports."""

from typing import TYPE_CHECKING, Any

from sim_pilot.runtime.action_attempts import (
    ActionAttempt,
    ActionAttemptStatus,
    ReconciliationClassification,
    RecoveryResolution,
)
from sim_pilot.runtime.errors import DurablePersistenceError, ReconstructionConsistencyError
from sim_pilot.runtime.models import (
    RuntimeConfiguration,
    RuntimeEvent,
    RuntimeOutcome,
    RuntimeSafeguardState,
)
from sim_pilot.runtime.recovery import CrashPoint, ReconciliationReport

if TYPE_CHECKING:
    from sim_pilot.runtime.decisions import ScriptedDecisionProvider
    from sim_pilot.runtime.engine import RuntimeEngine
    from sim_pilot.runtime.events import EventStore, InMemoryEventStore
    from sim_pilot.runtime.reconstruction import (
        ReconstructedRuntimeContext,
        RuntimeReconstructor,
    )

__all__ = [
    "ActionAttempt",
    "ActionAttemptStatus",
    "CrashPoint",
    "DurablePersistenceError",
    "EventStore",
    "InMemoryEventStore",
    "ReconstructedRuntimeContext",
    "ReconciliationClassification",
    "ReconciliationReport",
    "ReconstructionConsistencyError",
    "RuntimeConfiguration",
    "RuntimeEngine",
    "RuntimeEvent",
    "RuntimeOutcome",
    "RuntimeReconstructor",
    "RuntimeSafeguardState",
    "RecoveryResolution",
    "ScriptedDecisionProvider",
]


def __getattr__(name: str) -> Any:
    if name == "RuntimeEngine":
        from sim_pilot.runtime.engine import RuntimeEngine

        return RuntimeEngine
    if name == "ScriptedDecisionProvider":
        from sim_pilot.runtime.decisions import ScriptedDecisionProvider

        return ScriptedDecisionProvider
    if name in {"EventStore", "InMemoryEventStore"}:
        from sim_pilot.runtime.events import EventStore, InMemoryEventStore

        return {"EventStore": EventStore, "InMemoryEventStore": InMemoryEventStore}[name]
    if name in {"ReconstructedRuntimeContext", "RuntimeReconstructor"}:
        from sim_pilot.runtime.reconstruction import (
            ReconstructedRuntimeContext,
            RuntimeReconstructor,
        )

        return {
            "ReconstructedRuntimeContext": ReconstructedRuntimeContext,
            "RuntimeReconstructor": RuntimeReconstructor,
        }[name]
    raise AttributeError(name)
