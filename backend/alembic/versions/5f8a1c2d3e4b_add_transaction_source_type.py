"""add transaction source type

Revision ID: 5f8a1c2d3e4b
Revises: 4d7e8f9a0b1c
Create Date: 2026-05-12 21:25:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5f8a1c2d3e4b"
down_revision: Union[str, None] = "4d7e8f9a0b1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "source_type",
            sa.String(length=50),
            nullable=False,
            server_default="vatbook",
        ),
    )
    op.create_index(
        "idx_transactions_user_source_date",
        "transactions",
        ["user_id", "source_type", "transaction_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_transactions_user_source_date", table_name="transactions")
    op.drop_column("transactions", "source_type")
