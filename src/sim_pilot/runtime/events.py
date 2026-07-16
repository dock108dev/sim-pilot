"""Append-only runtime event-store interface and in-memory implementation."""

from collections import defaultdict
from typing import Protocol
from uuid import UUID

from sim_pilot.runtime.models import RuntimeEvent


class EventStore(Protocol):
    def append(self, event: RuntimeEvent) -> None: ...

    def list_events(self, task_id: UUID) -> tuple[RuntimeEvent, ...]: ...

    def latest(self, task_id: UUID) -> RuntimeEvent | None: ...


class InMemoryEventStore:
    """Append-only task streams with strict per-task sequencing."""

    def __init__(self) -> None:
        self._events: dict[UUID, list[RuntimeEvent]] = defaultdict(list)

    def append(self, event: RuntimeEvent) -> None:
        stream = self._events[event.task_id]
        expected = len(stream) + 1
        if event.sequence != expected:
            msg = f"expected event sequence {expected}, received {event.sequence}"
            raise ValueError(msg)
        stream.append(event)

    def list_events(self, task_id: UUID) -> tuple[RuntimeEvent, ...]:
        return tuple(self._events.get(task_id, ()))

    def latest(self, task_id: UUID) -> RuntimeEvent | None:
        stream = self._events.get(task_id)
        return stream[-1] if stream else None
