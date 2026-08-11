"""observability (sprint 3.6): traces + trace_spans + tasks.trace_id

Revision ID: a1b2c3d4e5ff
Revises: a1b2c3d4e5fe
Create Date: 2026-08-11 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "a1b2c3d4e5ff"
down_revision: Union[str, None] = "a1b2c3d4e5fe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "traces" not in inspector.get_table_names():
        op.create_table(
            "traces",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "company_id",
                UUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "conversation_id",
                UUID(as_uuid=True),
                sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                nullable=True,
            ),
            # Plain UUID for now: FK to trace_spans is added after that table
            # exists (traces <-> trace_spans are mutually referencing).
            sa.Column("root_span_id", UUID(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source", sa.String(40), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_traces_company_id", "traces", ["company_id"])
        op.create_index("ix_traces_conversation_id", "traces", ["conversation_id"])

    if "trace_spans" not in inspector.get_table_names():
        op.create_table(
            "trace_spans",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "trace_id",
                UUID(as_uuid=True),
                sa.ForeignKey("traces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "parent_span_id",
                UUID(as_uuid=True),
                sa.ForeignKey("trace_spans.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("span_type", sa.String(30), nullable=False),
            sa.Column("name", sa.String(240), nullable=False),
            sa.Column(
                "agent_id",
                UUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "task_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "supplier_id",
                UUID(as_uuid=True),
                sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "order_id",
                UUID(as_uuid=True),
                sa.ForeignKey("orders.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=False),
            sa.Column("error_kind", sa.String(40), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_trace_spans_trace_id", "trace_spans", ["trace_id"])
        op.create_index("ix_trace_spans_parent_span_id", "trace_spans", ["parent_span_id"])
        op.create_index("ix_trace_spans_task_id", "trace_spans", ["task_id"])
        op.create_index("ix_trace_spans_agent_id", "trace_spans", ["agent_id"])
        op.create_index("ix_trace_spans_supplier_id", "trace_spans", ["supplier_id"])
        op.create_index("ix_trace_spans_order_id", "trace_spans", ["order_id"])
        op.create_index(
            "ix_trace_spans_trace_parent",
            "trace_spans",
            ["trace_id", "parent_span_id"],
        )

        # Now the circular FK traces.root_span_id -> trace_spans.id is safe.
        op.create_foreign_key(
            "fk_traces_root_span_id",
            "traces",
            "trace_spans",
            ["root_span_id"],
            ["id"],
            ondelete="SET NULL",
        )

    task_cols = {c["name"] for c in inspector.get_columns("tasks")}
    if "trace_id" not in task_cols:
        op.add_column(
            "tasks",
            sa.Column(
                "trace_id",
                UUID(as_uuid=True),
                sa.ForeignKey("traces.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_tasks_trace_id", "tasks", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_trace_id", table_name="tasks")
    op.drop_column("tasks", "trace_id")
    op.drop_constraint("fk_traces_root_span_id", "traces", type_="foreignkey")
    op.drop_table("trace_spans")
    op.drop_table("traces")
