"""add invoice document projection fields

Revision ID: 1c2b3f4d5e6f
Revises: 7b9e8d1f4c2a
Create Date: 2026-05-11 22:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1c2b3f4d5e6f"
down_revision: Union[str, None] = "7b9e8d1f4c2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("document_id", sa.Uuid(), nullable=True))
    op.add_column("invoices", sa.Column("reference", sa.String(length=255), nullable=True))
    op.add_column("invoices", sa.Column("vat_amount", sa.Numeric(), nullable=True))
    op.alter_column("invoices", "currency", existing_type=sa.String(length=3), nullable=True)
    op.create_foreign_key(
        "fk_invoices_document_id_documents",
        "invoices",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("idx_invoices_document_id", "invoices", ["document_id"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_invoices_document_id", table_name="invoices")
    op.drop_constraint("fk_invoices_document_id_documents", "invoices", type_="foreignkey")
    op.alter_column("invoices", "currency", existing_type=sa.String(length=3), nullable=False)
    op.drop_column("invoices", "vat_amount")
    op.drop_column("invoices", "reference")
    op.drop_column("invoices", "document_id")
