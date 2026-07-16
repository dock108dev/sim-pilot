"""Public orchestration API for the standalone reference simulation."""

from uuid import NAMESPACE_URL, uuid5

from sim_pilot.domain import ExecutionResult
from sim_pilot.reference_simulation.actions import (
    AdvanceTime,
    BuildHousing,
    BuildPower,
    Pause,
    RepairInfrastructure,
    RepayLoan,
    SetMaintenance,
    SimulationAction,
    TakeLoan,
)
from sim_pilot.reference_simulation.projects import Project, ProjectType
from sim_pilot.reference_simulation.state import (
    EventType,
    SimulationEvent,
    SimulationState,
    initial_state,
)
from sim_pilot.reference_simulation.tick import advance_tick
from sim_pilot.reference_simulation.validation import ValidationResult, validate_action


class ReferenceSimulation:
    """A deterministic, serializable simulation engine."""

    def __init__(self, state: SimulationState | None = None, *, seed: int | str = 0) -> None:
        self._state = state or initial_state()
        self._seed = str(seed)
        self._events: list[SimulationEvent] = []
        self._last_events: tuple[SimulationEvent, ...] = ()

    @property
    def state(self) -> SimulationState:
        return self._state

    @property
    def events(self) -> tuple[SimulationEvent, ...]:
        return tuple(self._events)

    @property
    def last_events(self) -> tuple[SimulationEvent, ...]:
        return self._last_events

    @property
    def seed(self) -> str:
        return self._seed

    def validate(self, action: SimulationAction) -> ValidationResult:
        """Validate without changing state or event history."""
        return validate_action(self._state, action)

    def execute(self, action: SimulationAction) -> ExecutionResult:
        """Validate and execute one simulation action."""
        validation = self.validate(action)
        if not validation.valid:
            self._last_events = ()
            return ExecutionResult(
                success=False,
                state_changed=False,
                cost=0.0,
                message=validation.message,
            )

        previous_state = self._state
        new_events: list[SimulationEvent] = []

        def emit(type_: EventType, details: dict[str, None | bool | int | float | str]) -> None:
            new_events.append(
                SimulationEvent(
                    sequence=len(self._events) + len(new_events) + 1,
                    tick=self._state.tick,
                    type=type_,
                    details=details,
                )
            )

        if isinstance(action, AdvanceTime):
            for _ in range(action.ticks):
                result = advance_tick(
                    self._state,
                    event_sequence=len(self._events) + len(new_events),
                )
                self._state = result.state
                new_events.extend(result.events)
                if self._state.failed:
                    break
        elif isinstance(action, (BuildHousing, BuildPower)):
            project_type = (
                ProjectType.HOUSING if isinstance(action, BuildHousing) else ProjectType.POWER
            )
            amount = action.units if isinstance(action, BuildHousing) else action.capacity
            duration = 5 if project_type is ProjectType.HOUSING else 8
            project = Project(
                id=uuid5(
                    NAMESPACE_URL,
                    f"sim-pilot:{self._seed}:{self._state.tick}:{project_type.value}:"
                    f"{len(self._state.active_projects)}:{amount}",
                ),
                type=project_type,
                amount=amount,
                progress=0,
                duration=duration,
                remaining_ticks=duration,
                total_cost=validation.estimated_cost,
            )
            self._state = self._state.model_copy(
                update={
                    "cash": round(self._state.cash - validation.estimated_cost, 6),
                    "active_projects": (*self._state.active_projects, project),
                }
            )
            emit(
                EventType.PROJECT_STARTED,
                {
                    "project_id": str(project.id),
                    "project_type": project.type.value,
                    "amount": amount,
                    "cost": validation.estimated_cost,
                },
            )
            emit(
                EventType.CASH_CHANGED,
                {"previous": previous_state.cash, "current": self._state.cash},
            )
        elif isinstance(action, RepairInfrastructure):
            infrastructure = min(100.0, self._state.infrastructure + action.amount)
            self._state = self._state.model_copy(
                update={
                    "cash": round(self._state.cash - validation.estimated_cost, 6),
                    "infrastructure": round(infrastructure, 6),
                }
            )
            emit(
                EventType.INFRASTRUCTURE_CHANGED,
                {"previous": previous_state.infrastructure, "current": self._state.infrastructure},
            )
            emit(
                EventType.CASH_CHANGED,
                {"previous": previous_state.cash, "current": self._state.cash},
            )
        elif isinstance(action, SetMaintenance):
            self._state = self._state.model_copy(update={"maintenance_level": action.level})
            emit(
                EventType.MAINTENANCE_CHANGED,
                {"previous": previous_state.maintenance_level, "current": action.level},
            )
        elif isinstance(action, TakeLoan):
            self._state = self._state.model_copy(
                update={
                    "cash": round(self._state.cash + action.amount, 6),
                    "debt": round(self._state.debt + action.amount, 6),
                }
            )
            emit(
                EventType.CASH_CHANGED,
                {"previous": previous_state.cash, "current": self._state.cash},
            )
            emit(
                EventType.DEBT_CHANGED,
                {"previous": previous_state.debt, "current": self._state.debt},
            )
        elif isinstance(action, RepayLoan):
            self._state = self._state.model_copy(
                update={
                    "cash": round(self._state.cash - action.amount, 6),
                    "debt": round(self._state.debt - action.amount, 6),
                }
            )
            emit(
                EventType.CASH_CHANGED,
                {"previous": previous_state.cash, "current": self._state.cash},
            )
            emit(
                EventType.DEBT_CHANGED,
                {"previous": previous_state.debt, "current": self._state.debt},
            )
        elif isinstance(action, Pause):
            self._state = self._state.model_copy(update={"paused": True})
            emit(EventType.SIMULATION_PAUSED, {"paused": True})
        else:
            self._state = self._state.model_copy(update={"paused": False})
            emit(EventType.SIMULATION_RESUMED, {"paused": False})

        self._last_events = tuple(new_events)
        self._events.extend(new_events)
        changed = self._state != previous_state
        message = (
            "Action executed; simulation entered terminal failure."
            if self._state.failed and not previous_state.failed
            else "Action executed successfully."
        )
        return ExecutionResult(
            success=True,
            state_changed=changed,
            cost=validation.estimated_cost,
            message=message,
        )

    def to_json(self) -> str:
        """Serialize the current state to canonical JSON."""
        return self._state.model_dump_json()

    @classmethod
    def from_json(cls, payload: str, *, seed: int | str = 0) -> "ReferenceSimulation":
        """Restore a simulation from a version-validated state payload."""
        return cls(SimulationState.model_validate_json(payload), seed=seed)
