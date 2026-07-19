"""Typed dependency bundle shared by runtime execution collaborators."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sim_pilot.adapters.base import AdapterSnapshot, SimulationAdapter
from sim_pilot.domain import Observation, Task, TaskStatus
from sim_pilot.persistence import TaskRecord
from sim_pilot.runtime.decision_context import DecisionContextProjector
from sim_pilot.runtime.evaluator import ProgressEvaluator
from sim_pilot.runtime.models import RuntimeConfiguration, RuntimeSafeguardState
from sim_pilot.runtime.persistence import (
    EventDraft,
    RepositoryEventView,
    RuntimePersistence,
)
from sim_pilot.runtime.policy import PolicyEngine
from sim_pilot.runtime.reconstruction import ReconstructedRuntimeContext
from sim_pilot.runtime.recovery import CrashPoint
from sim_pilot.runtime.verification import ActionVerifier


@dataclass(frozen=True)
class RuntimeExecutionServices:
    """Dependencies and callbacks required by the execution coordinator."""

    persistence: RuntimePersistence
    configuration: RuntimeConfiguration
    decision_context_projector: DecisionContextProjector
    cancellation_check: Callable[[UUID], bool]
    evaluator: ProgressEvaluator
    policy: PolicyEngine
    verifier: ActionVerifier
    event_store: RepositoryEventView
    reconstruct: Callable[[UUID], ReconstructedRuntimeContext]
    load_or_create: Callable[[Task], ReconstructedRuntimeContext]
    gate_recovery: Callable[[ReconstructedRuntimeContext], ReconstructedRuntimeContext]
    crash: Callable[[CrashPoint], None]
    commit_terminal: Callable[
        [
            TaskRecord,
            RuntimeSafeguardState,
            SimulationAdapter,
            Observation,
            TaskStatus,
            str,
            tuple[EventDraft, ...],
        ],
        tuple[TaskRecord, str],
    ]
    commit_with_drafts: Callable[
        [
            TaskRecord,
            Task,
            RuntimeSafeguardState,
            tuple[EventDraft, ...],
            AdapterSnapshot | None,
        ],
        TaskRecord,
    ]
    observation_history: Callable[[UUID], tuple[Observation, ...]]
