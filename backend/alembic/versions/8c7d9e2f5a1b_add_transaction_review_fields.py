"""add transaction review fields

Revision ID: 8c7d9e2f5a1b
Revises: 5f8a1c2d3e4b
Create Date: 2026-05-12 23:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8c7d9e2f5a1b"
down_revision: str | Sequence[str] | None = "5f8a1c2d3e4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column("transactions", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("transactions", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.alter_column("transactions", "review_status", server_default=None)


def downgrade() -> None:
    op.drop_column("transactions", "reviewed_at")
    op.drop_column("transactions", "review_note")
    op.drop_column("transactions", "review_status")
