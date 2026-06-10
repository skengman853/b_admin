"""add reconciliation suggestions

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-06-09 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a9b8c7d6e5f4"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suggestion_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="suggested"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("reason_summary", sa.Text(), nullable=True),
        sa.Column("reason_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("verifier_status", sa.String(length=20), nullable=True),
        sa.Column("extractor_version", sa.String(length=50), nullable=True),
        sa.Column("matcher_version", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_reconciliation_suggestions_transaction",
        "reconciliation_suggestions",
        ["transaction_id", "status", "created_at"],
    )
    op.create_index(
        "idx_reconciliation_suggestions_user",
        "reconciliation_suggestions",
        ["user_id", "status", "created_at"],
    )
    op.create_index(
        "idx_reconciliation_suggestions_type",
        "reconciliation_suggestions",
        ["suggestion_type", "status", "created_at"],
    )

    op.create_table(
        "reconciliation_suggestion_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("financial_row_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("item_role", sa.String(length=50), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("signed_amount", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["financial_row_id"], ["document_financial_rows.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["suggestion_id"], ["reconciliation_suggestions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_reconciliation_suggestion_items_suggestion",
        "reconciliation_suggestion_items",
        ["suggestion_id", "item_role"],
    )
    op.create_index(
        "idx_reconciliation_suggestion_items_document",
        "reconciliation_suggestion_items",
        ["document_id"],
    )
    op.create_index(
        "idx_reconciliation_suggestion_items_financial_row",
        "reconciliation_suggestion_items",
        ["financial_row_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_reconciliation_suggestion_items_financial_row", table_name="reconciliation_suggestion_items")
    op.drop_index("idx_reconciliation_suggestion_items_document", table_name="reconciliation_suggestion_items")
    op.drop_index("idx_reconciliation_suggestion_items_suggestion", table_name="reconciliation_suggestion_items")
    op.drop_table("reconciliation_suggestion_items")

    op.drop_index("idx_reconciliation_suggestions_type", table_name="reconciliation_suggestions")
    op.drop_index("idx_reconciliation_suggestions_user", table_name="reconciliation_suggestions")
    op.drop_index("idx_reconciliation_suggestions_transaction", table_name="reconciliation_suggestions")
    op.drop_table("reconciliation_suggestions")
