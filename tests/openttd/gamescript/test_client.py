import asyncio
import json

import pytest

from sim_pilot.openttd.gamescript.client import GameScriptBridgeClient
from sim_pilot.openttd.gamescript.errors import BridgeSequenceError
from sim_pilot.openttd.gamescript.messages import MessageType
from sim_pilot.openttd.gamescript.models import BridgeHealth, SynchronizationState
from tests.openttd.gamescript.helpers import (
    FakeBridgeTransport,
    command_messages,
    message,
    snapshot,
    sync_messages,
    world_sync_messages,
)


def test_initial_negotiation_and_snapshot_synchronize() -> None:
    async def scenario() -> tuple[GameScriptBridgeClient, FakeBridgeTransport]:
        transport = FakeBridgeTransport(sync_messages())
        client = GameScriptBridgeClient(transport, company_id=0)
        await client.synchronize()
        return client, transport

    client, transport = asyncio.run(scenario())
    assert client.health.synchronization_state is SynchronizationState.SYNCHRONIZED
    assert client.health.snapshot is not None
    assert client.health.snapshot.town_count == 12
    assert client.health.capabilities is not None
    assert client.health.capabilities.state_deltas is False
    assert transport.subscriptions == 1


def test_protocol_v2_assembles_a_complete_paginated_world() -> None:
    async def scenario() -> GameScriptBridgeClient:
        client = GameScriptBridgeClient(FakeBridgeTransport(world_sync_messages()), company_id=0)
        await client.synchronize()
        return client

    client = asyncio.run(scenario())
    world = client.health.world_snapshot
    assert world is not None
    assert world.complete is True
    assert world.capture_completed_game_date == 712224
    assert [town.name for town in world.towns] == ["Town"]
    assert [vehicle.name for vehicle in world.vehicles] == ["Train 1"]


def test_protocol_v2_handles_empty_and_multiple_entity_worlds() -> None:
    async def empty_scenario() -> GameScriptBridgeClient:
        values = world_sync_messages()
        manifest = json.loads(values[4])
        manifest["payload"]["collection_counts"] = {
            key: 0 for key in manifest["payload"]["collection_counts"]
        }
        complete = json.loads(values[-1])
        complete["sequence"] = 6
        complete["message_id"] = "bridge-instance:6"
        complete["payload"]["total_items"] = 0
        client = GameScriptBridgeClient(
            FakeBridgeTransport([*values[:4], json.dumps(manifest), json.dumps(complete)]),
            company_id=0,
        )
        await client.synchronize()
        return client

    empty = asyncio.run(empty_scenario()).health.world_snapshot
    assert empty is not None
    assert empty.companies == ()
    assert empty.towns == ()

    async def multiple_scenario() -> GameScriptBridgeClient:
        values = world_sync_messages()
        manifest = json.loads(values[4])
        manifest["payload"]["collection_counts"]["companies"] = 2
        manifest["payload"]["collection_counts"]["towns"] = 2
        companies = json.loads(values[5])
        second_company = {**companies["payload"]["items"][0], "id": 1, "name": "Second"}
        companies["payload"]["items"].append(second_company)
        towns = json.loads(values[6])
        second_town = {**towns["payload"]["items"][0], "id": 2, "name": "Second Town"}
        towns["payload"]["items"].append(second_town)
        complete = json.loads(values[-1])
        complete["payload"]["total_items"] += 2
        values[4] = json.dumps(manifest)
        values[5] = json.dumps(companies)
        values[6] = json.dumps(towns)
        values[-1] = json.dumps(complete)
        client = GameScriptBridgeClient(FakeBridgeTransport(values), company_id=0)
        await client.synchronize()
        return client

    multiple = asyncio.run(multiple_scenario()).health.world_snapshot
    assert multiple is not None
    assert [company.name for company in multiple.companies] == ["Fixture Transport", "Second"]
    assert [town.name for town in multiple.towns] == ["Town", "Second Town"]


def test_protocol_v2_rejects_manifest_count_mismatch() -> None:
    async def scenario() -> None:
        values = world_sync_messages()
        manifest = json.loads(values[4])
        manifest["payload"]["collection_counts"]["vehicles"] = 2
        values[4] = json.dumps(manifest)
        client = GameScriptBridgeClient(FakeBridgeTransport(values), company_id=0)
        with pytest.raises(BridgeSequenceError, match="vehicles count"):
            await client.synchronize()

    asyncio.run(scenario())


def test_sequence_gap_duplicate_and_identity_change_fail_outside_resync() -> None:
    async def sequence_gap() -> None:
        transport = FakeBridgeTransport(sync_messages())
        client = GameScriptBridgeClient(transport, company_id=0)
        await client.synchronize()
        transport.messages.append(message(7, MessageType.STATE_SNAPSHOT, snapshot()))
        with pytest.raises(BridgeSequenceError, match="expected 5"):
            await client._receive()  # pyright: ignore[reportPrivateUsage]

    asyncio.run(sequence_gap())

    async def duplicate() -> None:
        transport = FakeBridgeTransport(sync_messages())
        client = GameScriptBridgeClient(transport, company_id=0)
        await client.synchronize()
        duplicate_message = message(5, MessageType.STATE_SNAPSHOT, snapshot())
        transport.messages.extend((duplicate_message, duplicate_message))
        await client._receive()  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(BridgeSequenceError, match="duplicate bridge message"):
            await client._receive()  # pyright: ignore[reportPrivateUsage]

    asyncio.run(duplicate())


def test_resume_rejects_a_different_script_instance_as_a_new_game() -> None:
    async def scenario() -> BridgeHealth:
        first = GameScriptBridgeClient(
            FakeBridgeTransport(sync_messages(instance_id="saved-game")), company_id=0
        )
        prior = await first.synchronize()
        resumed = GameScriptBridgeClient(
            FakeBridgeTransport(sync_messages(instance_id="different-game")),
            company_id=0,
            prior_health=prior,
            reject_instance_change=True,
        )
        with pytest.raises(BridgeSequenceError, match="different game"):
            await resumed.synchronize(reason="runtime_resume")
        return resumed.health

    health = asyncio.run(scenario())
    assert health.synchronization_state is SynchronizationState.FAILED


def test_approved_command_requires_opt_in_and_verifies_fresh_snapshot() -> None:
    async def scenario() -> tuple[str, str]:
        transport = FakeBridgeTransport(sync_messages())
        client = GameScriptBridgeClient(transport, company_id=0, allow_writes=True)
        await client.synchronize()
        request_id = "sim-pilot:test-request"
        command_id = "durable-command"
        name = "New Company Name"

        original_send = transport.send_gamescript

        async def send(value: str) -> None:
            parsed = json.loads(value)
            if parsed["message_type"] == "command_request":
                parsed_request_id = parsed["message_id"]
                transport.messages.extend(
                    command_messages(
                        sequence=5,
                        correlation=parsed_request_id,
                        command_id=command_id,
                        name=name,
                    )
                )
                transport.messages.extend(sync_messages(7, name=name))
            await original_send(value)

        transport.send_gamescript = send  # type: ignore[method-assign]
        completed, fresh = await client.execute_set_company_name(
            name=name,
            command_id=command_id,
            prior_snapshot_id="bridge:snapshot:4",
        )
        del request_id
        assert fresh.company is not None
        return completed.after_name, fresh.company.name

    assert asyncio.run(scenario()) == ("New Company Name", "New Company Name")


def test_close_is_clean() -> None:
    async def scenario() -> tuple[GameScriptBridgeClient, FakeBridgeTransport]:
        transport = FakeBridgeTransport(sync_messages())
        client = GameScriptBridgeClient(transport, company_id=0)
        await client.synchronize()
        await client.close()
        return client, transport

    client, transport = asyncio.run(scenario())
    assert transport.closed is True
    assert client.health.synchronization_state is SynchronizationState.DISCONNECTED
