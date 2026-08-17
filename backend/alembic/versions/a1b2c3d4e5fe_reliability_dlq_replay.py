"""reliability (sprint 3.5): dead_tasks table + tasks.replayed_from_task_id

Revision ID: a1b2c3d4e5fe
Revises: a1b2c3d4e5fd
Create Date: 2026-08-08 14:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "a1b2c3d4e5fe"
down_revision: Union[str, None] = "a1b2c3d4e5fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_cols = {c["name"] for c in inspector.get_columns("tasks")}
    if "replayed_from_task_id" not in task_cols:
        op.add_column(
            "tasks",
            sa.Column(
                "replayed_from_task_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_tasks_replayed_from_task_id", "tasks", ["replayed_from_task_id"]
        )
    if "dead_tasks" in inspector.get_table_names():
        return
    op.create_table(
        "dead_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("exception_kind", sa.String(30), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("dead_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "replayed_task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dead_tasks_task_id", "dead_tasks", ["task_id"], unique=True)
    op.create_index("ix_dead_tasks_company_id", "dead_tasks", ["company_id"])
    op.create_index("ix_dead_tasks_agent_id", "dead_tasks", ["agent_id"])
    op.create_index("ix_dead_tasks_replayed_task_id", "dead_tasks", ["replayed_task_id"])


def downgrade() -> None:
    op.drop_table("dead_tasks")
    op.drop_index("ix_tasks_replayed_from_task_id", table_name="tasks")
    op.drop_column("tasks", "replayed_from_task_id")
