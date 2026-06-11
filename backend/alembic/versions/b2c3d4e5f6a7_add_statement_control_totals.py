"""add statement control totals and arithmetic status to financial facts

Revision ID: b2c3d4e5f6a7
Revises: a9b8c7d6e5f4
Create Date: 2026-06-10 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a9b8c7d6e5f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_financial_facts", sa.Column("opening_balance", sa.Numeric(), nullable=True))
    op.add_column("document_financial_facts", sa.Column("closing_balance", sa.Numeric(), nullable=True))
    op.add_column("document_financial_facts", sa.Column("total_due", sa.Numeric(), nullable=True))
    op.add_column("document_financial_facts", sa.Column("settlement_discount_total", sa.Numeric(), nullable=True))
    op.add_column("document_financial_facts", sa.Column("arithmetic_mode", sa.String(length=20), nullable=True))
    op.add_column("document_financial_facts", sa.Column("arithmetic_status", sa.String(length=20), nullable=True))
    op.add_column("document_financial_facts", sa.Column("arithmetic_delta", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_financial_facts", "arithmetic_delta")
    op.drop_column("document_financial_facts", "arithmetic_status")
    op.drop_column("document_financial_facts", "arithmetic_mode")
    op.drop_column("document_financial_facts", "settlement_discount_total")
    op.drop_column("document_financial_facts", "total_due")
    op.drop_column("document_financial_facts", "closing_balance")
    op.drop_column("document_financial_facts", "opening_balance")
