"""Explicitly gated live acceptance tests for the production GameScript bridge."""

import asyncio
import json
import os

import pytest

from sim_pilot.adapters.openttd import OpenTTDAdapter
from sim_pilot.domain import Action
from sim_pilot.openttd import OpenTTDAdminClient, openttd_configuration
from sim_pilot.openttd.gamescript.client import GameScriptBridgeClient
from sim_pilot.openttd.gamescript.models import SynchronizationState
from sim_pilot.openttd.models import OpenTTDObservationState


def _require_live_bridge() -> None:
    if os.getenv("SIM_PILOT_LIVE_OPENTTD_GS") != "1":
        pytest.skip("set SIM_PILOT_LIVE_OPENTTD_GS=1 for the disposable OpenTTD server")


@pytest.mark.live
def test_live_bridge_snapshot_and_process_reconnect_preserve_identity() -> None:
    _require_live_bridge()

    async def synchronize_once() -> tuple[str | None, int, int]:
        configuration = openttd_configuration()
        admin = OpenTTDAdminClient(configuration)
        bridge = GameScriptBridgeClient(admin, company_id=configuration.company_id)
        adapter = OpenTTDAdapter(admin, bridge=bridge)
        await adapter.initialize()
        try:
            observation = await adapter.observe()
            assert bridge.health.synchronization_state is SynchronizationState.SYNCHRONIZED
            assert bridge.health.snapshot is not None
            assert bridge.health.snapshot.town_count >= 1
            return (
                bridge.health.script_instance_id,
                bridge.health.last_sequence or 0,
                observation.tick,
            )
        finally:
            await adapter.shutdown()

    first = asyncio.run(synchronize_once())
    second = asyncio.run(synchronize_once())
    assert second[0] == first[0]
    assert second[1] > first[1]
    assert second[2] >= first[2]


@pytest.mark.live
def test_live_bridge_company_name_action_is_verified_and_restored() -> None:
    _require_live_bridge()
    if os.getenv("SIM_PILOT_OPENTTD_GS_ALLOW_WRITES") != "1":
        pytest.skip("set SIM_PILOT_OPENTTD_GS_ALLOW_WRITES=1 for the disposable server")

    async def scenario() -> None:
        configuration = openttd_configuration()
        admin = OpenTTDAdminClient(configuration)
        bridge = GameScriptBridgeClient(
            admin,
            company_id=configuration.company_id,
            allow_writes=True,
        )
        adapter = OpenTTDAdapter(admin, bridge=bridge, allow_gamescript_writes=True)
        await adapter.initialize()
        try:
            before = await adapter.observe()
            resources = OpenTTDObservationState.model_validate_json(
                json.dumps(before.state)
            ).resources
            original = resources.company_name
            assert isinstance(original, str)
            temporary = "Sim Pilot Task 7B Live"
            action = Action(
                type="set_company_name",
                parameters={"name": temporary},
                expected_effect="Set and independently observe the company name.",
            )
            assert (await adapter.validate(action)).valid
            assert (await adapter.execute(action)).success
            changed = await adapter.observe()
            changed_resources = OpenTTDObservationState.model_validate_json(
                json.dumps(changed.state)
            ).resources
            assert changed_resources.company_name == temporary
            restore = action.model_copy(update={"parameters": {"name": original}})
            assert (await adapter.execute(restore)).success
            restored = await adapter.observe()
            restored_resources = OpenTTDObservationState.model_validate_json(
                json.dumps(restored.state)
            ).resources
            assert restored_resources.company_name == original
        finally:
            await adapter.shutdown()

    asyncio.run(scenario())
