"""Typed OpenTTD state and resource mapping tests."""

from sim_pilot.openttd.models import OpenTTDObservationState, OpenTTDResourceMapping
from tests.openttd.helpers import fixture, fixtures, state


def test_recorded_fixture_catalog_covers_required_scenarios() -> None:
    assert {item["scenario"] for item in fixtures()} == {
        "initial_company",
        "profitable_company",
        "loss_making_company",
        "paused_game",
        "company_with_vehicles",
        "company_with_stopped_vehicle",
        "loan_balance",
        "disconnected_response",
        "unsupported_version_response",
        "missing_company_response",
    }


def test_unavailable_admin_fields_are_explicit_in_scenario_fixtures() -> None:
    assert fixture("paused_game")["unavailable_fields"] == ["paused"]
    assert fixture("company_with_stopped_vehicle")["unavailable_fields"] == [
        "active_vehicles",
        "stopped_vehicles",
    ]


def test_resource_mapping_preserves_signs_and_nullable_fields() -> None:
    mapping = OpenTTDResourceMapping.from_state(state("loss_making_company"))

    assert mapping.cash == -25_000
    assert mapping.debt == 300_000
    assert mapping.profit == -75_000
    assert mapping.income is None
    assert mapping.expenses is None


def test_observation_state_round_trips_as_strict_json() -> None:
    observation_state = OpenTTDObservationState.from_game_state(state())

    restored = OpenTTDObservationState.model_validate_json(observation_state.model_dump_json())

    assert restored == observation_state
    assert restored.resources.vehicle_count == 19
    assert restored.resources.station_count == 16
    assert restored.adapter.capabilities.execute_actions is False
