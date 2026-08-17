"""core base schema: companies/users/agents/tasks/memories

Root migration. Replaces the implicit ``Base.metadata.create_all`` that the
dev fast-path used for the ten core tables. Must run before any conversation /
intake / sales migration because those declare foreign keys to ``companies``
and ``users``.

Revision ID: a0b1c2d3e4f0
Revises:
Create Date: 2026-08-14 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a0b1c2d3e4f0"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # Base schema mirrors the ORM models at sprint-1 state. Columns introduced
    # later (companies.settings/shadow_mode/public_token, users.role/
    # must_change_password/company_id, tasks.trace_id/replayed_from_task_id)
    # are added by their own migrations further down the chain.
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("slug", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("agent_quota", sa.Integer(), nullable=False, server_default="10"),
        *_timestamps(),
    )
    op.create_index("ix_companies_slug", "companies", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(180), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("hashed_password", sa.String(255), nullable=False, server_default=""),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        *_timestamps(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "type",
            sa.Enum("system", "general", "specialized", name="agent_type"),
            nullable=False,
            server_default="general",
        ),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("model", sa.String(120), nullable=False, server_default="gpt-4o-mini"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column(
            "status",
            sa.Enum("idle", "active", "paused", "disabled", "failed", name="agent_status"),
            nullable=False,
            server_default="idle",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("tasks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_success_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_llm_calls", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
    )
    op.create_index("ix_agents_company_id", "agents", ["company_id"])
    op.create_index("ix_agents_slug", "agents", ["slug"], unique=True)

    op.create_table(
        "agent_tools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("agent_id", "tool_name"),
        *_timestamps(),
    )
    op.create_index("ix_agent_tools_agent_id", "agent_tools", ["agent_id"])

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "queued",
                "running",
                "awaiting_routing",
                "completed",
                "failed",
                "cancelled",
                name="task_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "priority",
            sa.Enum("low", "normal", "high", "urgent", name="task_priority"),
            nullable=False,
            server_default="normal",
        ),
        sa.Column("input_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("routing_decision", sa.JSON(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_tasks_company_id", "tasks", ["company_id"])
    op.create_index("ix_tasks_agent_id", "tasks", ["agent_id"])

    op.create_table(
        "task_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(80), nullable=False, server_default="orchestrator"),
        sa.Column("level", sa.String(20), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])
    op.create_index("ix_task_events_agent_id", "task_events", ["agent_id"])

    op.create_table(
        "knowledge_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
    )
    op.create_index("ix_knowledge_entries_company_id", "knowledge_entries", ["company_id"])

    op.create_table(
        "short_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(60), nullable=False, server_default="interaction"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_short_memories_agent_id", "short_memories", ["agent_id"])

    op.create_table(
        "long_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(60), nullable=False, server_default="lesson"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "source_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        *_timestamps(),
    )
    op.create_index("ix_long_memories_agent_id", "long_memories", ["agent_id"])

    op.create_table(
        "memory_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_type",
            sa.Enum("short", "long", "knowledge", name="memory_type"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
    )
    op.create_index("ix_memory_entries_agent_id", "memory_entries", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_entries_agent_id", table_name="memory_entries")
    op.drop_table("memory_entries")
    op.drop_index("ix_long_memories_agent_id", table_name="long_memories")
    op.drop_table("long_memories")
    op.drop_index("ix_short_memories_agent_id", table_name="short_memories")
    op.drop_table("short_memories")
    op.drop_index("ix_knowledge_entries_company_id", table_name="knowledge_entries")
    op.drop_table("knowledge_entries")
    op.drop_index("ix_task_events_agent_id", table_name="task_events")
    op.drop_index("ix_task_events_task_id", table_name="task_events")
    op.drop_table("task_events")
    op.drop_index("ix_tasks_agent_id", table_name="tasks")
    op.drop_index("ix_tasks_company_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_agent_tools_agent_id", table_name="agent_tools")
    op.drop_table("agent_tools")
    op.drop_index("ix_agents_slug", table_name="agents")
    op.drop_index("ix_agents_company_id", table_name="agents")
    op.drop_table("agents")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_companies_slug", table_name="companies")
    op.drop_table("companies")

    for enum_name in [
        "memory_type",
        "task_priority",
        "task_status",
        "agent_status",
        "agent_type",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
