"""SQLAlchemy Core table metadata mirrored by Alembic migrations."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)

metadata = MetaData()

tasks = Table(
    "tasks",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("schema_version", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("specification_json", Text, nullable=False),
    Column("current_sequence", Integer, nullable=False),
    Column("total_spend", Text, nullable=False),
    Column("cancel_requested", Boolean, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    CheckConstraint("schema_version >= 1", name="ck_tasks_schema_version"),
    CheckConstraint("current_sequence >= 0", name="ck_tasks_current_sequence"),
)

events = Table(
    "events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("schema_version", Integer, nullable=False),
    Column("task_id", String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("timestamp", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    CheckConstraint("schema_version >= 1", name="ck_events_schema_version"),
    CheckConstraint("sequence >= 1", name="ck_events_sequence"),
    UniqueConstraint("task_id", "sequence", name="uq_events_task_sequence"),
)
Index("ix_events_task_sequence", events.c.task_id, events.c.sequence)

approvals = Table(
    "approvals",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("schema_version", Integer, nullable=False),
    Column("task_id", String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("action_json", Text, nullable=False),
    Column("reason", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("resolved_at", Text, nullable=True),
    CheckConstraint("schema_version >= 1", name="ck_approvals_schema_version"),
)
Index("ix_approvals_task_created", approvals.c.task_id, approvals.c.created_at)
Index(
    "uq_approvals_pending_action",
    approvals.c.task_id,
    approvals.c.action_json,
    unique=True,
    sqlite_where=text("status = 'pending'"),
)

simulation_checkpoints = Table(
    "simulation_checkpoints",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("schema_version", Integer, nullable=False),
    Column("task_id", String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
    Column("runtime_sequence", Integer, nullable=False),
    Column("simulation_tick", Integer, nullable=False),
    Column("simulation_schema_version", Integer, nullable=False),
    Column("state_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    CheckConstraint("schema_version >= 1", name="ck_checkpoints_schema_version"),
    CheckConstraint("runtime_sequence >= 0", name="ck_checkpoints_runtime_sequence"),
    CheckConstraint("simulation_tick >= 0", name="ck_checkpoints_simulation_tick"),
    CheckConstraint(
        "simulation_schema_version >= 1", name="ck_checkpoints_simulation_schema_version"
    ),
    UniqueConstraint("task_id", "runtime_sequence", name="uq_checkpoints_task_runtime_sequence"),
)
Index(
    "ix_checkpoints_task_latest",
    simulation_checkpoints.c.task_id,
    simulation_checkpoints.c.runtime_sequence,
)
