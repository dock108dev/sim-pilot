"""Persistence compatibility for observational OpenTTD records."""

import asyncio
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sim_pilot.adapters.openttd import OpenTTDReadOnlyAdapter
from sim_pilot.domain import Observation
from sim_pilot.domain.models import JsonValue
from sim_pilot.persistence import EventRecord, InMemoryUnitOfWork
from sim_pilot.runtime.models import RuntimeEvent, RuntimeEventType
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
