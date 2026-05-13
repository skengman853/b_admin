"""add transactions tables

Revision ID: 4d7e8f9a0b1c
Revises: 1c2b3f4d5e6f
Create Date: 2026-05-11 23:35:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4d7e8f9a0b1c"
down_revision: Union[str, None] = "1c2b3f4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_sheet", sa.String(length=255), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("posted_account", sa.String(length=255), nullable=True),
        sa.Column("pub", sa.String(length=255), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("description1", sa.Text(), nullable=True),
        sa.Column("description2", sa.Text(), nullable=True),
        sa.Column("debit_amount", sa.Numeric(), nullable=True),
        sa.Column("credit_amount", sa.Numeric(), nullable=True),
        sa.Column("transaction_type", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("resale_23_amount", sa.Numeric(), nullable=True),
        sa.Column("non_resale_23_amount", sa.Numeric(), nullable=True),
        sa.Column("non_resale_13_5_amount", sa.Numeric(), nullable=True),
        sa.Column("non_resale_9_amount", sa.Numeric(), nullable=True),
        sa.Column("non_resale_0_amount", sa.Numeric(), nullable=True),
        sa.Column("annotation_types", sa.JSON(), nullable=False),
        sa.Column("annotation_notes", sa.JSON(), nullable=False),
        sa.Column("has_linked_annotation", sa.Boolean(), nullable=False),
        sa.Column("raw_row_json", sa.JSON(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_transactions_user_date", "transactions", ["user_id", "transaction_date"], unique=False)
    op.create_index("idx_transactions_user_pub_date", "transactions", ["user_id", "pub", "transaction_date"], unique=False)
    op.create_index(
        "idx_transactions_source_row",
        "transactions",
        ["user_id", "source_file", "source_sheet", "row_number"],
        unique=True,
    )

    op.create_table(
        "transaction_document_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=True),
        sa.Column("match_reason", sa.Text(), nullable=True),
        sa.Column("amount_applied", sa.Numeric(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", "document_id", "role", name="uq_transaction_document_link"),
    )
    op.create_index(
        "idx_transaction_document_links_transaction",
        "transaction_document_links",
        ["transaction_id"],
        unique=False,
    )
    op.create_index(
        "idx_transaction_document_links_document",
        "transaction_document_links",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "idx_transaction_document_links_status",
        "transaction_document_links",
        ["user_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_transaction_document_links_status", table_name="transaction_document_links")
    op.drop_index("idx_transaction_document_links_document", table_name="transaction_document_links")
    op.drop_index("idx_transaction_document_links_transaction", table_name="transaction_document_links")
    op.drop_table("transaction_document_links")

    op.drop_index("idx_transactions_source_row", table_name="transactions")
    op.drop_index("idx_transactions_user_pub_date", table_name="transactions")
    op.drop_index("idx_transactions_user_date", table_name="transactions")
    op.drop_table("transactions")
