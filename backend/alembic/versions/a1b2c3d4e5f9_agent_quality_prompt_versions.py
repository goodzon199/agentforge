"""agent quality: prompt versions, llm usage, prompt_version columns

Revision ID: a1b2c3d4e5f9
Revises: a1b2c3d4e5f8
Create Date: 2026-08-07 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f9"
down_revision: Union[str, None] = "a1b2c3d4e5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    return column in [c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)]


def upgrade() -> None:
    if not _has_table("prompt_versions"):
        op.create_table(
            "prompt_versions",
            sa.Column("id", UUID, primary_key=True),
            sa.Column(
                "company_id",
                UUID,
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("agent_kind", sa.String(80), nullable=False),
            sa.Column("version", sa.String(40), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint(
                "company_id", "agent_kind", "version", name="uq_prompt_version"
            ),
        )
        op.create_index(
            "ix_prompt_versions_agent_kind", "prompt_versions", ["agent_kind"]
        )
        op.create_index(
            "ix_prompt_versions_company_id", "prompt_versions", ["company_id"]
        )

    if not _has_table("llm_usage"):
        op.create_table(
            "llm_usage",
            sa.Column("id", UUID, primary_key=True),
            sa.Column(
                "company_id",
                UUID,
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "agent_id",
                UUID,
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "task_id",
                UUID,
                sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("model", sa.String(120), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("estimated_cost_rub", sa.Numeric(12, 4), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_llm_usage_company_id", "llm_usage", ["company_id"])
        op.create_index("ix_llm_usage_agent_id", "llm_usage", ["agent_id"])
        op.create_index("ix_llm_usage_task_id", "llm_usage", ["task_id"])

    if not _has_column("quotes", "prompt_version"):
        op.add_column(
            "quotes",
            sa.Column("prompt_version", sa.String(40), nullable=True),
        )
    if not _has_column("agent_feedback", "prompt_version"):
        op.add_column(
            "agent_feedback",
            sa.Column("prompt_version", sa.String(40), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("agent_feedback", "prompt_version")
    op.drop_column("quotes", "prompt_version")
    op.drop_index("ix_llm_usage_task_id", table_name="llm_usage")
    op.drop_index("ix_llm_usage_agent_id", table_name="llm_usage")
    op.drop_index("ix_llm_usage_company_id", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_index("ix_prompt_versions_company_id", table_name="prompt_versions")
    op.drop_index("ix_prompt_versions_agent_kind", table_name="prompt_versions")
    op.drop_table("prompt_versions")
