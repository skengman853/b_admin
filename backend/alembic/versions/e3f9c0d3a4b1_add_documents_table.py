"""add documents table

Revision ID: e3f9c0d3a4b1
Revises: 824e6a858fd9
Create Date: 2026-05-07 13:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f9c0d3a4b1"
down_revision: Union[str, None] = "824e6a858fd9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("attachment_index", sa.Integer(), nullable=False),
        sa.Column("attachment_name", sa.String(length=255), nullable=False),
        sa.Column("supplier", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("review_reasons", sa.JSON(), nullable=False),
        sa.Column("source_email_sender", sa.Text(), nullable=True),
        sa.Column("source_email_subject", sa.Text(), nullable=True),
        sa.Column("source_received_at", sa.DateTime(), nullable=True),
        sa.Column("drive_file_id", sa.String(length=255), nullable=True),
        sa.Column("drive_web_link", sa.Text(), nullable=True),
        sa.Column("drive_folder_path", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_documents_lookup",
        "documents",
        ["user_id", "gmail_message_id", "attachment_index"],
        unique=True,
    )
    op.create_index("idx_documents_user_created", "documents", ["user_id", "created_at"], unique=False)
    op.create_index("idx_documents_user_review", "documents", ["user_id", "needs_review"], unique=False)
    op.create_index("idx_documents_user_synced", "documents", ["user_id", "synced_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_documents_user_synced", table_name="documents")
    op.drop_index("idx_documents_user_review", table_name="documents")
    op.drop_index("idx_documents_user_created", table_name="documents")
    op.drop_index("idx_documents_lookup", table_name="documents")
    op.drop_table("documents")
