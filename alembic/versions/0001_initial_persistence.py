"""Create initial durable persistence schema.

Revision ID: 0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("specification_json", sa.Text(), nullable=False),
        sa.Column("current_sequence", sa.Integer(), nullable=False),
        sa.Column("total_spend", sa.Text(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("current_sequence >= 0", name="ck_tasks_current_sequence"),
        sa.CheckConstraint("schema_version >= 1", name="ck_tasks_schema_version"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.CheckConstraint("schema_version >= 1", name="ck_events_schema_version"),
        sa.CheckConstraint("sequence >= 1", name="ck_events_sequence"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "sequence", name="uq_events_task_sequence"),
    )
    op.create_index("ix_events_task_sequence", "events", ["task_id", "sequence"])
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("action_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.Text(), nullable=True),
        sa.CheckConstraint("schema_version >= 1", name="ck_approvals_schema_version"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approvals_task_created", "approvals", ["task_id", "created_at"])
    op.create_index(
        "uq_approvals_pending_action",
        "approvals",
        ["task_id", "action_json"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "simulation_checkpoints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("runtime_sequence", sa.Integer(), nullable=False),
        sa.Column("simulation_tick", sa.Integer(), nullable=False),
        sa.Column("simulation_schema_version", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("schema_version >= 1", name="ck_checkpoints_schema_version"),
        sa.CheckConstraint("runtime_sequence >= 0", name="ck_checkpoints_runtime_sequence"),
        sa.CheckConstraint("simulation_tick >= 0", name="ck_checkpoints_simulation_tick"),
        sa.CheckConstraint(
            "simulation_schema_version >= 1", name="ck_checkpoints_simulation_schema_version"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id", "runtime_sequence", name="uq_checkpoints_task_runtime_sequence"
        ),
    )
    op.create_index(
        "ix_checkpoints_task_latest",
        "simulation_checkpoints",
        ["task_id", "runtime_sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_checkpoints_task_latest", table_name="simulation_checkpoints")
    op.drop_table("simulation_checkpoints")
    op.drop_index("uq_approvals_pending_action", table_name="approvals")
    op.drop_index("ix_approvals_task_created", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_events_task_sequence", table_name="events")
    op.drop_table("events")
    op.drop_table("tasks")
