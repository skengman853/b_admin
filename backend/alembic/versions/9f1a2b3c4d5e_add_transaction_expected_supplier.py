"""add transaction expected supplier

Revision ID: 9f1a2b3c4d5e
Revises: 8c7d9e2f5a1b
Create Date: 2026-05-14 09:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f1a2b3c4d5e"
down_revision = "8c7d9e2f5a1b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("expected_supplier", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "expected_supplier")
