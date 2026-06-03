"""add transaction rules

Revision ID: c9d8e7f6a5b4
Revises: b1c2d3e4f5a6
Create Date: 2026-05-23 12:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9d8e7f6a5b4"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transaction_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("pub", sa.String(length=255), nullable=True),
        sa.Column("match_field", sa.String(length=50), nullable=False),
        sa.Column("match_value", sa.String(length=255), nullable=False),
        sa.Column("display_label", sa.String(length=255), nullable=True),
        sa.Column("category_override", sa.String(length=255), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("expected_supplier", sa.String(length=255), nullable=True),
        sa.Column("document_expectation", sa.String(length=50), nullable=True),
        sa.Column("owner_note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_type",
            "pub",
            "match_field",
            "match_value",
            name="uq_transaction_rule_scope",
        ),
    )
    op.create_index(
        "idx_transaction_rules_user_active",
        "transaction_rules",
        ["user_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "idx_transaction_rules_lookup",
        "transaction_rules",
        ["user_id", "source_type", "pub", "match_field", "match_value"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_transaction_rules_lookup", table_name="transaction_rules")
    op.drop_index("idx_transaction_rules_user_active", table_name="transaction_rules")
    op.drop_table("transaction_rules")
