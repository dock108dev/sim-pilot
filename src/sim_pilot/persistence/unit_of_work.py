"""Storage-independent atomic persistence boundary."""

from types import TracebackType
from typing import Protocol, Self

from sim_pilot.persistence.repositories import (
    ApprovalRepository,
    EventRepository,
    SimulationRepository,
    TaskRepository,
)


class UnitOfWork(Protocol):
    """Coordinate all repositories inside one transaction."""

    @property
    def tasks(self) -> TaskRepository: ...

    @property
    def events(self) -> EventRepository: ...

    @property
    def approvals(self) -> ApprovalRepository: ...

    @property
    def simulations(self) -> SimulationRepository: ...

    def begin(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool: ...
