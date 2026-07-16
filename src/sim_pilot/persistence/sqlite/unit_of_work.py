"""SQLite transaction boundary shared by all durable repositories."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy import Connection, Engine
from sqlalchemy.engine import Transaction
from sqlalchemy.exc import SQLAlchemyError

from sim_pilot.persistence.errors import TransactionError
from sim_pilot.persistence.repositories import (
    ApprovalRepository,
    EventRepository,
    SimulationRepository,
    TaskRepository,
)
from sim_pilot.persistence.sqlite.migrations import verify_database_revision
from sim_pilot.persistence.sqlite.repositories import (
    SQLiteApprovalRepository,
    SQLiteEventRepository,
    SQLiteSimulationRepository,
    SQLiteTaskRepository,
)


class SQLiteUnitOfWork:
    """Expose four repositories over exactly one SQLite transaction."""

    def __init__(self, engine: Engine, *, verify_revision: bool = True) -> None:
        if verify_revision:
            verify_database_revision(engine)
        self._engine = engine
        self._connection: Connection | None = None
        self._transaction: Transaction | None = None
        self._tasks: SQLiteTaskRepository | None = None
        self._events: SQLiteEventRepository | None = None
        self._approvals: SQLiteApprovalRepository | None = None
        self._simulations: SQLiteSimulationRepository | None = None

    @property
    def tasks(self) -> TaskRepository:
        return self._require_repository(self._tasks)

    @property
    def events(self) -> EventRepository:
        return self._require_repository(self._events)

    @property
    def approvals(self) -> ApprovalRepository:
        return self._require_repository(self._approvals)

    @property
    def simulations(self) -> SimulationRepository:
        return self._require_repository(self._simulations)

    def begin(self) -> None:
        if self._connection is not None:
            raise TransactionError("unit of work is already active")
        try:
            connection = self._engine.connect()
            transaction = connection.begin()
        except SQLAlchemyError as error:
            raise TransactionError(f"could not begin transaction: {error}") from error
        self._connection = connection
        self._transaction = transaction
        self._tasks = SQLiteTaskRepository(connection)
        self._events = SQLiteEventRepository(connection)
        self._approvals = SQLiteApprovalRepository(connection)
        self._simulations = SQLiteSimulationRepository(connection)

    def commit(self) -> None:
        connection, transaction = self._require_transaction()
        try:
            transaction.commit()
        except SQLAlchemyError as error:
            if transaction.is_active:
                transaction.rollback()
            raise TransactionError(f"could not commit transaction: {error}") from error
        finally:
            connection.close()
            self._clear()

    def rollback(self) -> None:
        connection, transaction = self._require_transaction()
        try:
            transaction.rollback()
        except SQLAlchemyError as error:
            raise TransactionError(f"could not roll back transaction: {error}") from error
        finally:
            connection.close()
            self._clear()

    def __enter__(self) -> SQLiteUnitOfWork:
        self.begin()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    @staticmethod
    def _require_repository[RepositoryT](repository: RepositoryT | None) -> RepositoryT:
        if repository is None:
            raise TransactionError("unit of work is not active")
        return repository

    def _require_transaction(self) -> tuple[Connection, Transaction]:
        if self._connection is None or self._transaction is None:
            raise TransactionError("unit of work is not active")
        return self._connection, self._transaction

    def _clear(self) -> None:
        self._connection = None
        self._transaction = None
        self._tasks = None
        self._events = None
        self._approvals = None
        self._simulations = None
