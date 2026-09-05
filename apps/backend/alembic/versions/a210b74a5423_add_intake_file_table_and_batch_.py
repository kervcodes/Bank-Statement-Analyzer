"""add intake file table and batch validation_failed column

Revision ID: a210b74a5423
Revises: 514aa3a0a621
Create Date: 2026-09-05 01:21:23.916438

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a210b74a5423"
down_revision: str | Sequence[str] | None = "514aa3a0a621"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "intake_file",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("batch_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "original_filename", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("failure_reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("temp_path", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACCEPTED', 'UPLOAD_FAILED', 'VALIDATION_FAILED')",
            name="ck_intake_file_status",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["batch.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_intake_file_batch_id"), "intake_file", ["batch_id"], unique=False
    )
    op.add_column("batch", sa.Column("validation_failed", sa.Integer(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("batch", "validation_failed")
    op.drop_index(op.f("ix_intake_file_batch_id"), table_name="intake_file")
    op.drop_table("intake_file")
