"""Contract tests for the runtime-facing reference adapter."""

import asyncio
from decimal import Decimal

import pytest

from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.domain import Action
from sim_pilot.domain.models import JsonValue


def action(type_: str, parameters: dict[str, JsonValue] | None = None) -> Action:
    return Action(
        type=type_,
        parameters=parameters or {},
        expected_effect="Deterministic simulation state changes.",
        estimated_cost=Decimal(0),
    )


def test_adapter_observation_contract() -> None:
    async def scenario() -> None:
        adapter = ReferenceSimulationAdapter()
        await adapter.initialize()

        first = await adapter.observe()
        second = await adapter.observe()

        assert first.sequence == 1
        assert second.sequence == 2
        assert first.timestamp.tzinfo is not None
        assert first.tick == adapter.simulation.state.tick
        assert first.state == adapter.simulation.state.model_dump(mode="json")
        assert first.summary.startswith("Tick 0:")

    asyncio.run(scenario())


def test_adapter_lists_all_actions() -> None:
    async def scenario() -> None:
        adapter = ReferenceSimulationAdapter()
        await adapter.initialize()

        definitions = await adapter.available_actions()

        assert {definition.type for definition in definitions} == {
            "advance_time",
            "build_housing",
            "build_power",
            "repair",
            "set_maintenance",
            "take_loan",
            "repay_loan",
            "pause",
            "resume",
        }

    asyncio.run(scenario())


def test_adapter_validation_and_execution() -> None:
    async def scenario() -> None:
        adapter = ReferenceSimulationAdapter()
        await adapter.initialize()
        build = action("build_housing", {"units": 100})

        validation = await adapter.validate(build)
        result = await adapter.execute(build)

        assert validation.valid is True
        assert validation.estimated_cost == 100_000
        assert result.success is True
        assert result.cost == 100_000
        assert adapter.simulation.state.cash == 400_000

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "invalid_action",
    [
        action("build_housing", {"units": 0}),
        action("advance_time", {"ticks": -1}),
        action("set_maintenance", {"level": 0.25}),
        action("unknown"),
    ],
)
def test_adapter_rejects_malformed_actions(invalid_action: Action) -> None:
    async def scenario() -> None:
        adapter = ReferenceSimulationAdapter()
        await adapter.initialize()
        original = adapter.simulation.state

        validation = await adapter.validate(invalid_action)
        result = await adapter.execute(invalid_action)

        assert validation.valid is False
        assert result.success is False
        assert adapter.simulation.state == original

    asyncio.run(scenario())


def test_scenario_c_adapter_rejects_forbidden_loan() -> None:
    async def scenario() -> None:
        adapter = ReferenceSimulationAdapter(forbidden_actions=frozenset({"take_loan"}))
        await adapter.initialize()
        loan = action("take_loan", {"amount": 100_000.0})

        validation = await adapter.validate(loan)
        result = await adapter.execute(loan)

        assert validation.valid is False
        assert "forbidden" in validation.message
        assert result.success is False
        assert adapter.simulation.state.debt == 0

    asyncio.run(scenario())


def test_adapter_shutdown_rejects_further_operations() -> None:
    async def scenario() -> None:
        adapter = ReferenceSimulationAdapter()
        await adapter.initialize()
        await adapter.shutdown()

        with pytest.raises(RuntimeError, match="not initialized"):
            await adapter.observe()

    asyncio.run(scenario())
