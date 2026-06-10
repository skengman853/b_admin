"""add document extraction runs

Revision ID: e8f1a2b3c4d5
Revises: d4e5f6a7b8c9
Create Date: 2026-06-06 15:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f1a2b3c4d5"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_extraction_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extractor_family", sa.String(length=50), nullable=False),
        sa.Column("extractor_profile", sa.String(length=100), nullable=True),
        sa.Column("extractor_version", sa.String(length=50), nullable=False),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("review_reasons", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("raw_payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_document_extraction_runs_document",
        "document_extraction_runs",
        ["document_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_document_extraction_runs_user",
        "document_extraction_runs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_document_extraction_runs_status",
        "document_extraction_runs",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_document_extraction_runs_status", table_name="document_extraction_runs")
    op.drop_index("idx_document_extraction_runs_user", table_name="document_extraction_runs")
    op.drop_index("idx_document_extraction_runs_document", table_name="document_extraction_runs")
    op.drop_table("document_extraction_runs")
