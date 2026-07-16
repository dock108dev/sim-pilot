"""Pure one-tick state transition for the reference simulation."""

from dataclasses import dataclass

from sim_pilot.reference_simulation.economy import (
    calculate_income,
    calculate_population_growth,
    debt_expense,
    infrastructure_degradation,
    maintenance_cost,
)
from sim_pilot.reference_simulation.projects import Project, ProjectType, progress_project
from sim_pilot.reference_simulation.state import (
    EventType,
    FailureCode,
    SimulationEvent,
    SimulationFailure,
    SimulationState,
)


@dataclass(frozen=True, slots=True)
class TickResult:
    """State and events produced by one tick."""

    state: SimulationState
    events: tuple[SimulationEvent, ...]
    failure: SimulationFailure | None


def failure_for_state(state: SimulationState) -> SimulationFailure | None:
    """Return the first canonical terminal failure present in state."""
    if state.cash < 0:
        return SimulationFailure(
            code=FailureCode.NEGATIVE_CASH,
            message="Cash fell below zero.",
        )
    if state.infrastructure <= 0:
        return SimulationFailure(
            code=FailureCode.INFRASTRUCTURE_DEPLETED,
            message="Infrastructure reached zero.",
        )
    if state.debt > 2_000_000:
        return SimulationFailure(
            code=FailureCode.DEBT_LIMIT_EXCEEDED,
            message="Debt exceeded the maximum of 2000000.",
        )
    return None


def advance_tick(state: SimulationState, *, event_sequence: int = 0) -> TickResult:
    """Advance state by one tick in the exact RFC-002 processing order."""
    if state.paused or state.failed:
        msg = "Cannot advance a paused or failed simulation."
        raise ValueError(msg)

    tick = state.tick + 1
    events: list[SimulationEvent] = []

    def emit(type_: EventType, details: dict[str, None | bool | int | float | str]) -> None:
        events.append(
            SimulationEvent(
                sequence=event_sequence + len(events) + 1,
                tick=tick,
                type=type_,
                details=details,
            )
        )

    emit(EventType.TICK_ADVANCED, {"tick": tick})

    active_projects: list[Project] = []
    housing = state.housing
    power_capacity = state.power_capacity
    for project in state.active_projects:
        progressed = progress_project(project)
        emit(
            EventType.PROJECT_PROGRESSED,
            {
                "project_id": str(project.id),
                "remaining_ticks": progressed.remaining_ticks,
            },
        )
        if progressed.remaining_ticks == 0:
            if progressed.type is ProjectType.HOUSING:
                housing += progressed.amount
            else:
                power_capacity += progressed.amount
            emit(
                EventType.PROJECT_COMPLETED,
                {
                    "project_id": str(project.id),
                    "project_type": progressed.type.value,
                    "amount": progressed.amount,
                },
            )
        else:
            active_projects.append(progressed)

    power_usage_before_growth = state.population
    growth_state = state.model_copy(
        update={
            "tick": tick,
            "housing": housing,
            "power_capacity": power_capacity,
            "power_usage": power_usage_before_growth,
            "active_projects": tuple(active_projects),
        }
    )
    growth = calculate_population_growth(growth_state)
    population = state.population + growth
    if growth:
        emit(
            EventType.POPULATION_CHANGED,
            {"previous": state.population, "current": population, "growth": growth},
        )

    income_state = growth_state.model_copy(update={"population": population})
    income = calculate_income(income_state)
    maintenance = maintenance_cost(state.maintenance_level)
    debt = debt_expense(state.debt)
    expense = round(maintenance + debt, 6)
    cash = round(state.cash + income - expense, 6)
    if cash != state.cash:
        emit(
            EventType.CASH_CHANGED,
            {"previous": state.cash, "current": cash, "income": income, "expense": expense},
        )

    infrastructure = max(
        0.0,
        round(state.infrastructure - infrastructure_degradation(state.maintenance_level), 6),
    )
    if infrastructure != state.infrastructure:
        emit(
            EventType.INFRASTRUCTURE_CHANGED,
            {"previous": state.infrastructure, "current": infrastructure},
        )

    next_state = SimulationState(
        tick=tick,
        cash=cash,
        debt=state.debt,
        population=population,
        housing=housing,
        power_capacity=power_capacity,
        power_usage=population,
        infrastructure=infrastructure,
        maintenance_level=state.maintenance_level,
        income_per_tick=income,
        expense_per_tick=expense,
        paused=False,
        failed=False,
        active_projects=tuple(active_projects),
    )
    failure = failure_for_state(next_state)
    if failure is not None:
        next_state = next_state.model_copy(update={"failed": True, "paused": True})
        emit(
            EventType.SIMULATION_FAILED,
            {"code": failure.code.value, "message": failure.message},
        )

    return TickResult(state=next_state, events=tuple(events), failure=failure)
