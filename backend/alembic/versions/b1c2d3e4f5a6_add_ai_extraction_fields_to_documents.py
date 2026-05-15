"""add ai extraction fields to documents

Revision ID: b1c2d3e4f5a6
Revises: a4b5c6d7e8f9
Create Date: 2026-05-15 17:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("ai_extraction_status", sa.String(length=20), nullable=True))
    op.add_column("documents", sa.Column("ai_extraction_provider", sa.String(length=50), nullable=True))
    op.add_column("documents", sa.Column("ai_extraction_model", sa.String(length=100), nullable=True))
    op.add_column("documents", sa.Column("ai_extraction_payload", sa.JSON(), nullable=True))
    op.add_column("documents", sa.Column("ai_extracted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "ai_extracted_at")
    op.drop_column("documents", "ai_extraction_payload")
    op.drop_column("documents", "ai_extraction_model")
    op.drop_column("documents", "ai_extraction_provider")
    op.drop_column("documents", "ai_extraction_status")
