"""Read-only OpenTTD adapter contract tests."""

import asyncio
import json
from datetime import UTC

from sim_pilot.adapters.base import ActionDefinition, SimulationAdapter
from sim_pilot.adapters.openttd import (
    OpenTTDAdapter,
    OpenTTDReadOnlyAdapter,
    OpenTTDValidation,
)
from sim_pilot.domain import Action, ExecutionResult, Observation
from sim_pilot.openttd.gamescript.client import GameScriptBridgeClient
from sim_pilot.openttd.models import OpenTTDObservationState
from tests.openttd.gamescript.helpers import FakeBridgeTransport, sync_messages
from tests.openttd.helpers import FakeOpenTTDClient, state


def test_adapter_satisfies_contract_and_returns_two_observations() -> None:
    async def scenario() -> tuple[Observation, Observation, OpenTTDReadOnlyAdapter]:
        client = FakeOpenTTDClient([state("initial_company"), state("profitable_company")])
        adapter = OpenTTDReadOnlyAdapter(client)
        typed: SimulationAdapter = adapter
        await typed.initialize()
        first = await typed.observe()
        second = await typed.observe()
        return first, second, adapter

    first, second, adapter = asyncio.run(scenario())

    assert first.sequence == 1
    assert second.sequence == 2
    assert second.tick >= first.tick
    assert first.timestamp.tzinfo is UTC
    assert second.summary == (
        "OpenTTD 1951-01-01: company=0 cash=425000 loan=50000 profit=175000 "
        "vehicles=19 facilities=16"
    )
    assert adapter.capabilities.read_state is True


def test_adapter_advertises_no_actions_and_rejects_without_client_interaction() -> None:
    async def scenario() -> tuple[int, bool, bool, OpenTTDReadOnlyAdapter, FakeOpenTTDClient]:
        client = FakeOpenTTDClient()
        adapter = OpenTTDReadOnlyAdapter(client)
        await adapter.initialize()
        action = Action(type="pause", expected_effect="Pause the game.")
        actions = await adapter.available_actions()
        validation = await adapter.validate(action)
        result = await adapter.execute(action)
        await adapter.shutdown()
        return len(actions), validation.valid, result.success, adapter, client

    action_count, valid, success, adapter, client = asyncio.run(scenario())

    assert action_count == 0
    assert valid is False
    assert success is False
    assert client.collect_calls == 1
    assert client.closed is True
    assert adapter.capabilities.supports_restore is False


def test_write_opt_in_advertises_and_verifies_server_name_action() -> None:
    async def scenario() -> tuple[
        list[ActionDefinition],
        OpenTTDValidation,
        ExecutionResult,
        Observation,
        Observation,
        FakeOpenTTDClient,
    ]:
        client = FakeOpenTTDClient()
        adapter = OpenTTDAdapter(client, allow_writes=True)
        action = Action(
            type="set_server_name",
            parameters={"name": "Sim Pilot Test"},
            expected_effect="Set the server name.",
        )
        await adapter.initialize()
        before = await adapter.observe()
        definitions = await adapter.available_actions()
        validation = await adapter.validate(action)
        result = await adapter.execute(action)
        after = await adapter.observe()
        await adapter.shutdown()
        return (definitions, validation, result, after, before, client)

    definitions, validation, result, after, before, client = asyncio.run(scenario())

    assert [definition.type for definition in definitions] == ["set_server_name"]
    assert validation.valid is True
    assert result.success is True
    assert result.state_changed is True
    assert before.state["resources"]["server_name"] == "Fixture Server"  # type: ignore[index]
    assert after.state["resources"]["server_name"] == "Sim Pilot Test"  # type: ignore[index]
    assert client.rcon_commands == ['server_name "Sim Pilot Test"']
    assert client.reconnect_calls == 1


def test_stale_economy_rejects_action_without_rcon() -> None:
    async def scenario() -> tuple[OpenTTDValidation, FakeOpenTTDClient]:
        client = FakeOpenTTDClient([state("initial_company"), state("profitable_company")])
        adapter = OpenTTDAdapter(client, allow_writes=True)
        action = Action(
            type="set_server_name",
            parameters={"name": "Sim Pilot Test"},
            expected_effect="Set the server name.",
        )
        await adapter.initialize()
        await adapter.observe()
        validation = await adapter.validate(action)
        await adapter.shutdown()
        return validation, client

    validation, client = asyncio.run(scenario())

    assert validation.valid is False
    assert validation.state_stale is True
    assert validation.code == "stale_observation"
    assert client.rcon_commands == []


def test_adapter_combines_bridge_snapshot_and_negotiates_live_actions() -> None:
    async def scenario() -> tuple[Observation, list[ActionDefinition]]:
        admin = FakeOpenTTDClient()
        bridge = GameScriptBridgeClient(
            FakeBridgeTransport(sync_messages()),
            company_id=0,
            allow_writes=True,
        )
        adapter = OpenTTDAdapter(
            admin,
            bridge=bridge,
            allow_gamescript_writes=True,
        )
        await adapter.initialize()
        observation = await adapter.observe()
        actions = await adapter.available_actions()
        await adapter.shutdown()
        return observation, actions

    observation, actions = asyncio.run(scenario())
    combined = OpenTTDObservationState.model_validate_json(json.dumps(observation.state))
    assert combined.resources.town_count == 12
    assert combined.resources.industry_count == 8
    assert combined.bridge is not None
    assert combined.bridge.script_instance_id == "bridge-instance"
    assert combined.source_attribution.inconsistencies == ()
    assert [action.type for action in actions] == ["set_company_name"]
    assert "towns=12 industries=8 paused=False bridge=synchronized" in observation.summary


def test_bridge_actions_remain_absent_without_separate_write_opt_in() -> None:
    async def scenario() -> list[ActionDefinition]:
        admin = FakeOpenTTDClient()
        bridge = GameScriptBridgeClient(
            FakeBridgeTransport(sync_messages()),
            company_id=0,
        )
        adapter = OpenTTDAdapter(admin, bridge=bridge)
        await adapter.initialize()
        await adapter.observe()
        actions = await adapter.available_actions()
        await adapter.shutdown()
        return actions

    assert asyncio.run(scenario()) == []
