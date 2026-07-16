"""Add runtime safeguard and adapter restoration metadata.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(
            sa.Column("runtime_state_json", sa.Text(), nullable=False, server_default="{}")
        )
    with op.batch_alter_table("simulation_checkpoints") as batch_op:
        batch_op.add_column(
            sa.Column(
                "adapter_type", sa.String(length=128), nullable=False, server_default="reference"
            )
        )
        batch_op.add_column(
            sa.Column("adapter_schema_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column(
                "adapter_observation_sequence", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column("adapter_seed", sa.Text(), nullable=False, server_default="0")
        )
        batch_op.create_check_constraint(
            "ck_checkpoints_adapter_schema_version", "adapter_schema_version >= 1"
        )
        batch_op.create_check_constraint(
            "ck_checkpoints_adapter_observation_sequence",
            "adapter_observation_sequence >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("simulation_checkpoints") as batch_op:
        batch_op.drop_constraint("ck_checkpoints_adapter_observation_sequence", type_="check")
        batch_op.drop_constraint("ck_checkpoints_adapter_schema_version", type_="check")
        batch_op.drop_column("adapter_seed")
        batch_op.drop_column("adapter_observation_sequence")
        batch_op.drop_column("adapter_schema_version")
        batch_op.drop_column("adapter_type")
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("runtime_state_json")
