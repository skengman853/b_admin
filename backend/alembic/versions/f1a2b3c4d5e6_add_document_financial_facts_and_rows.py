"""add document financial facts and rows

Revision ID: f1a2b3c4d5e6
Revises: e8f1a2b3c4d5
Create Date: 2026-06-06 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e8f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_financial_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_canonical", sa.String(length=255), nullable=False),
        sa.Column("pub_hint", sa.String(length=255), nullable=True),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("statement_kind", sa.String(length=100), nullable=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("vat_amount", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("account_number", sa.String(length=255), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("is_financial", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_primary_version", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["document_extraction_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_document_financial_facts_document"),
    )
    op.create_index(
        "idx_document_financial_facts_user_type_date",
        "document_financial_facts",
        ["user_id", "document_type", "document_date"],
    )
    op.create_index(
        "idx_document_financial_facts_supplier_date",
        "document_financial_facts",
        ["supplier_canonical", "document_date"],
    )
    op.create_index(
        "idx_document_financial_facts_run",
        "document_financial_facts",
        ["extraction_run_id"],
    )

    op.create_table(
        "document_financial_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("row_type", sa.String(length=50), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("clearing_reference", sa.String(length=255), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("signed_amount", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("is_financial", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["document_extraction_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("extraction_run_id", "row_index", name="uq_document_financial_rows_run_row"),
    )
    op.create_index(
        "idx_document_financial_rows_document",
        "document_financial_rows",
        ["document_id", "row_index"],
    )
    op.create_index(
        "idx_document_financial_rows_run",
        "document_financial_rows",
        ["extraction_run_id", "row_index"],
    )
    op.create_index(
        "idx_document_financial_rows_reference",
        "document_financial_rows",
        ["reference"],
    )
    op.create_index(
        "idx_document_financial_rows_clearing_reference",
        "document_financial_rows",
        ["clearing_reference"],
    )


def downgrade() -> None:
    op.drop_index("idx_document_financial_rows_clearing_reference", table_name="document_financial_rows")
    op.drop_index("idx_document_financial_rows_reference", table_name="document_financial_rows")
    op.drop_index("idx_document_financial_rows_run", table_name="document_financial_rows")
    op.drop_index("idx_document_financial_rows_document", table_name="document_financial_rows")
    op.drop_table("document_financial_rows")

    op.drop_index("idx_document_financial_facts_run", table_name="document_financial_facts")
    op.drop_index("idx_document_financial_facts_supplier_date", table_name="document_financial_facts")
    op.drop_index("idx_document_financial_facts_user_type_date", table_name="document_financial_facts")
    op.drop_table("document_financial_facts")
