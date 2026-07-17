"""Typed OpenTTD state and resource mapping tests."""

from sim_pilot.openttd.gamescript.models import BridgeHealth, SynchronizationState
from sim_pilot.openttd.models import (
    OpenTTDAdapterCapabilities,
    OpenTTDObservationState,
    OpenTTDResourceMapping,
)
from tests.openttd.gamescript.helpers import capabilities, snapshot
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


def test_combined_state_preserves_bridge_metadata_and_source_precedence() -> None:
    bridge_capabilities = capabilities()
    health = BridgeHealth(
        connected=True,
        authenticated=True,
        openttd_version="15.3",
        bridge_detected=True,
        bridge_protocol_version=1,
        script_version=1,
        script_instance_id="bridge-instance",
        last_sequence=4,
        synchronization_state=SynchronizationState.SYNCHRONIZED,
        active_company_context=0,
        capability_fingerprint=bridge_capabilities.fingerprint,
        capabilities=bridge_capabilities,
        snapshot=snapshot(),
    )
    combined = OpenTTDObservationState.from_combined_state(
        state(),
        health,
        OpenTTDAdapterCapabilities(
            bridge_detected=True,
            supports_full_snapshots=True,
            bridge_read_resources=bridge_capabilities.readable_resources,
            bridge_actions=bridge_capabilities.supported_actions,
        ),
    )
    restored = OpenTTDObservationState.model_validate_json(combined.model_dump_json())
    assert restored.bridge is not None
    assert restored.bridge.script_instance_id == "bridge-instance"
    assert restored.resources.cash == 425000
    assert restored.resources.town_count == 12
    assert restored.resources.industry_count == 8
    assert restored.source_attribution.inconsistencies == ()
