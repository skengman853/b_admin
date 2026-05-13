"""add document split fields

Revision ID: 7b9e8d1f4c2a
Revises: 2f6d6d6c43c1
Create Date: 2026-05-11 11:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b9e8d1f4c2a"
down_revision: Union[str, None] = "2f6d6d6c43c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("parent_document_id", sa.Uuid(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("derivation_index", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_foreign_key(
        "fk_documents_parent_document_id_documents",
        "documents",
        "documents",
        ["parent_document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("idx_documents_lookup", table_name="documents")
    op.create_index(
        "idx_documents_lookup",
        "documents",
        ["user_id", "gmail_message_id", "attachment_index", "derivation_index"],
        unique=True,
    )
    op.create_index("idx_documents_parent", "documents", ["parent_document_id"], unique=False)
    op.alter_column("documents", "derivation_index", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_documents_parent", table_name="documents")
    op.drop_index("idx_documents_lookup", table_name="documents")
    op.create_index(
        "idx_documents_lookup",
        "documents",
        ["user_id", "gmail_message_id", "attachment_index"],
        unique=True,
    )
    op.drop_constraint("fk_documents_parent_document_id_documents", "documents", type_="foreignkey")
    op.drop_column("documents", "derivation_index")
    op.drop_column("documents", "parent_document_id")
