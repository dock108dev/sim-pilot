"""Deterministic economic calculations for the reference simulation."""

from math import floor

from sim_pilot.reference_simulation.state import SimulationState

INCOME_PER_CITIZEN = 20.0
DEBT_EXPENSE_RATE = 0.001
MAINTENANCE_RULES: dict[float, tuple[float, float]] = {
    0.0: (0.0, 2.0),
    0.5: (2_500.0, 1.0),
    1.0: (5_000.0, 0.25),
}


def calculate_population_growth(state: SimulationState) -> int:
    """Calculate population growth using the canonical capacity rules."""
    if (
        state.paused
        or state.failed
        or state.infrastructure < 40
        or state.power_capacity < state.power_usage
        or state.housing <= state.population
    ):
        return 0
    base_growth = floor(state.population * 0.01)
    available_housing = state.housing - state.population
    available_power = max(state.power_capacity - state.power_usage, 0)
    return min(base_growth, available_housing, available_power)


def calculate_income(state: SimulationState) -> float:
    """Calculate income after infrastructure and power penalties."""
    base_income = state.population * INCOME_PER_CITIZEN
    infrastructure_multiplier = state.infrastructure / 100
    power_multiplier = 1.0 if state.power_capacity >= state.power_usage else 0.5
    return round(base_income * infrastructure_multiplier * power_multiplier, 6)


def maintenance_cost(level: float) -> float:
    """Return recurring maintenance expense for an allowed level."""
    return MAINTENANCE_RULES[level][0]


def infrastructure_degradation(level: float) -> float:
    """Return infrastructure degradation for an allowed level."""
    return MAINTENANCE_RULES[level][1]


def debt_expense(debt: float) -> float:
    """Return the recurring debt expense."""
    return round(debt * DEBT_EXPENSE_RATE, 6)
