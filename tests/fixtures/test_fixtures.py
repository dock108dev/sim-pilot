"""Sanity checks for deterministic reference simulation fixtures."""

import json
from pathlib import Path
from typing import cast

FIXTURE_ROOT = Path(__file__).parent
EXPECTED_FIELDS = {
    "schema_version",
    "tick",
    "cash",
    "debt",
    "population",
    "housing",
    "power_capacity",
    "power_usage",
    "infrastructure",
    "maintenance_level",
    "income_per_tick",
    "expense_per_tick",
    "paused",
    "active_projects",
}


def load_fixture(name: str) -> dict[str, object]:
    """Load one JSON fixture as a state mapping."""
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    return cast("dict[str, object]", value)


def test_fixtures_have_the_documented_state_shape() -> None:
    for path in FIXTURE_ROOT.glob("*.json"):
        state = load_fixture(path.name)
        assert set(state) == EXPECTED_FIELDS
        assert state["schema_version"] == 1


def test_fixture_scenarios_express_their_boundary_conditions() -> None:
    assert load_fixture("initial_state.json")["tick"] == 0
    assert load_fixture("cash_target_state.json")["cash"] == 1_000_000
    assert cast("int", load_fixture("bankrupt_state.json")["cash"]) < 0

    low_power = load_fixture("low_power_state.json")
    assert cast("int", low_power["power_usage"]) > cast("int", low_power["power_capacity"])
