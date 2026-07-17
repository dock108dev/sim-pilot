"""Read-only OpenTTD adapter contract tests."""

import asyncio
from datetime import UTC

from sim_pilot.adapters.base import SimulationAdapter
from sim_pilot.adapters.openttd import OpenTTDReadOnlyAdapter
from sim_pilot.domain import Action, Observation
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
