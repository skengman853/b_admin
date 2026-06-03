"""add document object storage fields

Revision ID: d4e5f6a7b8c9
Revises: c9d8e7f6a5b4
Create Date: 2026-05-31 16:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c9d8e7f6a5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("storage_provider", sa.String(length=20), nullable=True))
    op.add_column("documents", sa.Column("storage_bucket", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("storage_key", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("storage_synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "storage_synced_at")
    op.drop_column("documents", "storage_key")
    op.drop_column("documents", "storage_bucket")
    op.drop_column("documents", "storage_provider")
