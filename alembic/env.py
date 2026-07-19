"""Alembic migration environment for Sim Pilot SQLite databases."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from sim_pilot.config import database_url as configured_database_url
from sim_pilot.persistence.sqlite.database import secure_sqlite_files
from sim_pilot.persistence.sqlite.schema import metadata

config = context.config
if not config.attributes.get("sim_pilot_explicit_database_url"):
    config.set_main_option("sqlalchemy.url", configured_database_url())
if config.config_file_name is not None:
    # Migrations run in-process from the CLI and tests. Never disable application loggers as a
    # side effect of loading Alembic's console configuration.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database_url = config.get_main_option("sqlalchemy.url")
    secure_sqlite_files(database_url, create_database=True)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        with connectable.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            context.configure(
                connection=connection, target_metadata=target_metadata, render_as_batch=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()
        secure_sqlite_files(database_url)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
