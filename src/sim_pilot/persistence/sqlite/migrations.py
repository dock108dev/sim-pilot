"""Programmatic Alembic helpers for application setup and isolated tests."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from alembic import command
from sim_pilot.persistence.errors import UnsupportedSchemaVersionError

ALEMBIC_ROOT = Path(__file__).parents[4]
ALEMBIC_INI = ALEMBIC_ROOT / "alembic.ini"
HEAD_REVISION = "0002"


def alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def upgrade_database(database_url: str) -> None:
    """Upgrade an empty or previously migrated SQLite database to head."""
    command.upgrade(alembic_config(database_url), "head")


def verify_database_revision(engine: Engine) -> None:
    """Fail clearly when schema state is missing or unsupported."""
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables:
        raise UnsupportedSchemaVersionError("database has no Alembic migration state")
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    if revision != HEAD_REVISION:
        raise UnsupportedSchemaVersionError(
            f"database revision {revision!r} is unsupported; expected {HEAD_REVISION!r}"
        )
