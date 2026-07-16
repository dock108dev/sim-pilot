"""Storage-independent composition helpers for default local execution."""

from collections.abc import Callable

from sim_pilot.persistence.in_memory import InMemoryPersistenceState, InMemoryUnitOfWork
from sim_pilot.persistence.unit_of_work import UnitOfWork


def in_memory_unit_of_work_factory() -> Callable[[], UnitOfWork]:
    """Return a factory whose units of work share one in-memory state."""
    state = InMemoryPersistenceState()

    def create() -> UnitOfWork:
        return InMemoryUnitOfWork(state)

    return create
