"""add transaction review events

Revision ID: a4b5c6d7e8f9
Revises: 9f1a2b3c4d5e
Create Date: 2026-05-15 11:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "9f1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transaction_review_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("previous_review_status", sa.String(length=32), nullable=True),
        sa.Column("current_review_status", sa.String(length=32), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("link_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["link_id"], ["transaction_document_links.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_transaction_review_events_transaction",
        "transaction_review_events",
        ["transaction_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_transaction_review_events_user",
        "transaction_review_events",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_transaction_review_events_event_type",
        "transaction_review_events",
        ["event_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_transaction_review_events_event_type", table_name="transaction_review_events")
    op.drop_index("idx_transaction_review_events_user", table_name="transaction_review_events")
    op.drop_index("idx_transaction_review_events_transaction", table_name="transaction_review_events")
    op.drop_table("transaction_review_events")
