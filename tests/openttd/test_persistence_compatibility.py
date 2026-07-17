"""Persistence compatibility for observational OpenTTD records."""

import asyncio
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sim_pilot.adapters.openttd import OpenTTDAdapter, OpenTTDReadOnlyAdapter
from sim_pilot.domain import Observation
from sim_pilot.domain.models import JsonValue
from sim_pilot.openttd.gamescript.client import GameScriptBridgeClient
from sim_pilot.openttd.gamescript.models import BridgeHealth
from sim_pilot.openttd.models import OpenTTDObservationState
from sim_pilot.persistence import (
    CheckpointMetadata,
    EventRecord,
    InMemoryUnitOfWork,
    SimulationCheckpoint,
)
from sim_pilot.runtime.models import RuntimeEvent, RuntimeEventType
from tests.openttd.gamescript.helpers import FakeBridgeTransport, sync_messages
from tests.openttd.helpers import FakeOpenTTDClient
from tests.persistence.factories import TASK_ID, task_record


def test_observation_and_adapter_metadata_round_trip_through_event_repository() -> None:
    async def capture() -> Observation:
        adapter = OpenTTDReadOnlyAdapter(FakeOpenTTDClient())
        await adapter.initialize()
        try:
            return await adapter.observe()
        finally:
            await adapter.shutdown()

    observation = asyncio.run(capture())
    payload = cast("dict[str, JsonValue]", observation.model_dump(mode="json"))
    uow = InMemoryUnitOfWork()
    record = EventRecord(
        id=UUID("60000000-0000-0000-0000-000000000001"),
        event=RuntimeEvent(
            task_id=TASK_ID,
            sequence=1,
            event_type=RuntimeEventType.OBSERVATION_RECORDED,
            timestamp=datetime.now(UTC),
            payload={"observation": payload},
        ),
    )

    with uow:
        uow.tasks.create(task_record())
        uow.events.append(record)

    records: tuple[EventRecord, ...] = ()
    with uow:
        records = uow.events.list_for_task(TASK_ID)

    assert len(records) == 1
    restored_payload = records[0].event.payload["observation"]
    assert isinstance(restored_payload, dict)
    restored = Observation.model_validate_json(json.dumps(restored_payload))
    assert restored == observation
    assert restored.state["adapter"] == observation.state["adapter"]


def test_bridge_identity_and_sync_state_round_trip_in_existing_checkpoint_repository() -> None:
    async def capture() -> Observation:
        bridge = GameScriptBridgeClient(FakeBridgeTransport(sync_messages()), company_id=0)
        adapter = OpenTTDAdapter(FakeOpenTTDClient(), bridge=bridge)
        await adapter.initialize()
        try:
            return await adapter.observe()
        finally:
            await adapter.shutdown()

    observation = asyncio.run(capture())
    checkpoint = SimulationCheckpoint(
        metadata=CheckpointMetadata(
            id=UUID("60000000-0000-0000-0000-000000000002"),
            task_id=TASK_ID,
            runtime_sequence=1,
            simulation_tick=observation.tick,
            simulation_schema_version=1,
            adapter_type="openttd",
            adapter_observation_sequence=observation.sequence,
            adapter_seed="admin-map-12345",
            created_at=datetime.now(UTC),
        ),
        state=cast("dict[str, JsonValue]", observation.state),
    )
    uow = InMemoryUnitOfWork()
    with uow:
        uow.tasks.create(task_record())
        uow.simulations.save(checkpoint)
    restored: SimulationCheckpoint | None = None
    with uow:
        restored = uow.simulations.latest(TASK_ID)
    assert restored is not None
    typed = OpenTTDObservationState.model_validate_json(json.dumps(restored.state))
    assert typed.bridge is not None
    persisted_health = BridgeHealth.model_validate_json(typed.bridge.model_dump_json())
    assert persisted_health.script_instance_id == "bridge-instance"
    assert persisted_health.last_sequence == 4
    assert persisted_health.capability_fingerprint is not None
