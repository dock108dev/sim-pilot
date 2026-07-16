"""SQLite engine construction and connection invariants."""

from typing import Protocol

from sqlalchemy import Engine, create_engine, event


class _Cursor(Protocol):
    def execute(self, sql: str) -> object: ...

    def close(self) -> None: ...


class _DBAPIConnection(Protocol):
    def cursor(self) -> _Cursor: ...


def _enable_foreign_keys(dbapi_connection: _DBAPIConnection, connection_record: object) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_sqlite_engine(database_url: str) -> Engine:
    """Create an engine with SQLite foreign-key enforcement enabled."""
    if not database_url.startswith("sqlite:///"):
        msg = "SQLite database URL must start with sqlite:///"
        raise ValueError(msg)
    engine = create_engine(database_url)

    event.listen(engine, "connect", _enable_foreign_keys)
    return engine
