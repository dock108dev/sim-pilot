"""Shared repository contract backend factories."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest

from sim_pilot.persistence import InMemoryPersistenceState, InMemoryUnitOfWork, UnitOfWork
from sim_pilot.persistence.sqlite import SQLiteUnitOfWork, create_sqlite_engine, upgrade_database

type UnitOfWorkFactory = Callable[[], UnitOfWork]


@pytest.fixture(params=("memory", "sqlite"))
def uow_factory(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[UnitOfWorkFactory]:
    backend = cast("str", request.param)
    if backend == "memory":
        state = InMemoryPersistenceState()
        yield lambda: InMemoryUnitOfWork(state)
        return

    database_url = f"sqlite:///{tmp_path / 'contract.db'}"
    upgrade_database(database_url)
    engine = create_sqlite_engine(database_url)
    yield lambda: SQLiteUnitOfWork(engine)
    engine.dispose()
