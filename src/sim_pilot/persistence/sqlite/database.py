"""SQLite engine construction, permissions, and connection invariants."""

from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url


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


def sqlite_database_path(database_url: str) -> Path | None:
    """Return the local database path, or ``None`` for an in-memory database."""
    url = make_url(database_url)
    if url.drivername != "sqlite":
        raise ValueError("SQLite database URL must start with sqlite:///")
    if not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()


def secure_sqlite_files(database_url: str, *, create_database: bool = False) -> None:
    """Restrict a SQLite database and any rollback/WAL sidecars to its owner."""
    path = sqlite_database_path(database_url)
    if path is None:
        return
    if create_database and not path.exists():
        path.touch(mode=0o600)
    for suffix in ("", "-journal", "-shm", "-wal"):
        candidate = Path(f"{path}{suffix}")
        if candidate.exists():
            candidate.chmod(0o600)


def create_sqlite_engine(database_url: str) -> Engine:
    """Create an engine with SQLite foreign-key enforcement enabled."""
    sqlite_database_path(database_url)
    secure_sqlite_files(database_url)
    engine = create_engine(database_url)

    event.listen(engine, "connect", _enable_foreign_keys)

    def secure_files(*_: object) -> None:
        secure_sqlite_files(database_url)

    event.listen(engine, "connect", secure_files)
    event.listen(engine, "commit", secure_files)
    event.listen(engine, "rollback", secure_files)
    return engine
