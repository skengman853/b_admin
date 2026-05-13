"""add document extraction fields

Revision ID: 2f6d6d6c43c1
Revises: e3f9c0d3a4b1
Create Date: 2026-05-07 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2f6d6d6c43c1"
down_revision: Union[str, None] = "e3f9c0d3a4b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("vat_amount", sa.Numeric(), nullable=True))
    op.add_column("documents", sa.Column("currency", sa.String(length=3), nullable=True))
    op.add_column("documents", sa.Column("confidence_score", sa.Float(), nullable=True))
    op.add_column("documents", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("extraction_status", sa.String(length=20), server_default="pending", nullable=False),
    )
    op.add_column("documents", sa.Column("extracted_at", sa.DateTime(), nullable=True))
    op.alter_column("documents", "extraction_status", server_default=None)


def downgrade() -> None:
    op.drop_column("documents", "extracted_at")
    op.drop_column("documents", "extraction_status")
    op.drop_column("documents", "extracted_text")
    op.drop_column("documents", "confidence_score")
    op.drop_column("documents", "currency")
    op.drop_column("documents", "vat_amount")
