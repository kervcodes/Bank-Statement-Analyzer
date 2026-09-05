"""create canonical schema

Revision ID: 514aa3a0a621
Revises:
Create Date: 2026-09-04 23:18:55.206307

Money is stored as integer cents rather than NUMERIC: SQLite has no exact
decimal type and stores NUMERIC as a float, which loses precision at larger
magnitudes. See app/models/money.py.

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "514aa3a0a621"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "account",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("bank", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("account_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "account_identifier_masked",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "batch",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("selected", sa.Integer(), nullable=False),
        sa.Column("uploaded", sa.Integer(), nullable=False),
        sa.Column("upload_failed", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("processing_failed", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PROCESSING', 'COMPLETED', 'COMPLETED_WITH_WARNINGS', 'FAILED')",
            name="ck_batch_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "statement",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("batch_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("account_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("bank", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("account_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "account_identifier_masked",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
        ),
        sa.Column("statement_start_date", sa.Date(), nullable=False),
        sa.Column("statement_end_date", sa.Date(), nullable=False),
        sa.Column("opening_balance_cents", sa.Integer(), nullable=False),
        sa.Column("closing_balance_cents", sa.Integer(), nullable=False),
        sa.Column("parser_version", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "extraction_status", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "validation_result", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.CheckConstraint(
            "extraction_status IN ('SUCCESS', 'PARTIAL')",
            name="ck_statement_extraction_status",
        ),
        sa.CheckConstraint(
            "validation_result IS NULL OR "
            "validation_result IN ('VALID', 'WARNING', 'FAILED')",
            name="ck_statement_validation_result",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["batch.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_statement_account_id"), "statement", ["account_id"])
    op.create_index(op.f("ix_statement_batch_id"), "statement", ["batch_id"])
    op.create_table(
        "transaction",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("statement_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("account_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("posted_date", sa.Date(), nullable=False),
        sa.Column(
            "description_raw", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "description_normalized", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("direction", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("balance_after_cents", sa.Integer(), nullable=True),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("source_bank", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "direction IN ('DEBIT', 'CREDIT')", name="ck_transaction_direction"
        ),
        sa.CheckConstraint(
            "amount_cents >= 0", name="ck_transaction_amount_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["statement.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transaction_account_id"), "transaction", ["account_id"])
    op.create_index(
        op.f("ix_transaction_statement_id"), "transaction", ["statement_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_transaction_statement_id"), table_name="transaction")
    op.drop_index(op.f("ix_transaction_account_id"), table_name="transaction")
    op.drop_table("transaction")
    op.drop_index(op.f("ix_statement_batch_id"), table_name="statement")
    op.drop_index(op.f("ix_statement_account_id"), table_name="statement")
    op.drop_table("statement")
    op.drop_table("batch")
    op.drop_table("account")
