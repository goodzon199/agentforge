"""sales + approval: quotes, approvals, actions, feedback, user company

Revision ID: a1b2c3d4e5f6
Revises: 7f3b9c2d4e5a
Create Date: 2026-08-07 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "7f3b9c2d4e5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    quote_status = sa.Enum(
        "draft",
        "pending_approval",
        "approved",
        "sent",
        "accepted",
        "rejected",
        "expired",
        "converted_to_order",
        name="quote_status",
    )
    approval_status = sa.Enum(
        "pending", "approved", "rejected", "expired", "cancelled", name="approval_status"
    )
    risk_level = sa.Enum("low", "medium", "high", name="approval_risk_level")
    action_status = sa.Enum(
        "pending", "executed", "failed", "cancelled", name="agent_action_status"
    )
    feedback_type = sa.Enum(
        "approved_unchanged",
        "approved_edited",
        "rejected",
        "incorrect_fact",
        "bad_tone",
        "wrong_recommendation",
        name="agent_feedback_type",
    )

    op.add_column(
        "users",
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_users_company_id", "users", ["company_id"])

    op.create_table(
        "quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "part_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("part_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "best_offer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supplier_offers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", quote_status, nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="RUB"),
        sa.Column("quote_total", sa.Numeric(12, 2), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("ai_draft", sa.Text(), nullable=True),
        sa.Column("manager_edited", sa.Text(), nullable=True),
        sa.Column("final_message", sa.Text(), nullable=True),
        sa.Column("guard_status", sa.String(16), nullable=False, server_default="none"),
        sa.Column("guard_errors", sa.JSON(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_quotes_company_id", "quotes", ["company_id"])
    op.create_index("ix_quotes_part_request_id", "quotes", ["part_request_id"])
    op.create_index("ix_quotes_conversation_id", "quotes", ["conversation_id"])
    op.create_index("ix_quotes_best_offer_id", "quotes", ["best_offer_id"])

    op.create_table(
        "agent_actions",
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
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=True),
        sa.Column("target_id", sa.String(80), nullable=True),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("result_data", sa.JSON(), nullable=True),
        sa.Column("risk_level", risk_level, nullable=False, server_default="low"),
        sa.Column("status", action_status, nullable=False, server_default="pending"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_agent_actions_company_id", "agent_actions", ["company_id"])
    op.create_index("ix_agent_actions_action_type", "agent_actions", ["action_type"])
    op.create_index("ix_agent_actions_idempotency_key", "agent_actions", ["idempotency_key"])

    op.create_table(
        "approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "quote_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("quotes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("status", approval_status, nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("risk_level", risk_level, nullable=False, server_default="medium"),
        sa.Column(
            "requested_by_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "rejected_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_approval_requests_company_id", "approval_requests", ["company_id"])
    op.create_index("ix_approval_requests_quote_id", "approval_requests", ["quote_id"])
    op.create_index("ix_approval_requests_action_id", "approval_requests", ["action_id"])
    op.create_index(
        "ix_approval_requests_conversation_id", "approval_requests", ["conversation_id"]
    )
    op.create_index(
        "ix_approval_requests_requested_by_agent_id",
        "approval_requests",
        ["requested_by_agent_id"],
    )

    op.create_table(
        "agent_feedback",
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
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("feedback_type", feedback_type, nullable=False),
        sa.Column("original_output", sa.Text(), nullable=True),
        sa.Column("final_output", sa.Text(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_agent_feedback_company_id", "agent_feedback", ["company_id"])
    op.create_index("ix_agent_feedback_agent_id", "agent_feedback", ["agent_id"])


def downgrade() -> None:
    op.drop_table("agent_feedback")
    op.drop_table("approval_requests")
    op.drop_table("agent_actions")
    op.drop_table("quotes")
    op.drop_index("ix_users_company_id", table_name="users")
    op.drop_column("users", "company_id")
