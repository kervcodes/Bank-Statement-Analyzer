"""add statement_job.statement_id and account identity unique constraint

Revision ID: 69a3cd180f72
Revises: 06a9bc8c453d
Create Date: 2026-09-08 12:06:46.299250

build-plan #6. `statement_job.statement_id` links a completed job to the
`Statement` it produced (null for FAILED / UNSUPPORTED jobs -- REQ-VAL-005).
`uq_account_identity` makes "one Account per (bank, account_type, masked digits)"
a database invariant (REQ-ACC-002).

SQLite can't ALTER a table to add a constraint or a foreign key in place, so both
changes go through `batch_alter_table`, which rebuilds the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "69a3cd180f72"
down_revision: str | Sequence[str] | None = "06a9bc8c453d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_account_identity",
            ["bank", "account_type", "account_identifier_masked"],
        )

    with op.batch_alter_table("statement_job", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "statement_id",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_statement_job_statement_id"),
            ["statement_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_statement_job_statement_id_statement",
            "statement",
            ["statement_id"],
            ["id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("statement_job", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_statement_job_statement_id_statement", type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_statement_job_statement_id"))
        batch_op.drop_column("statement_id")

    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.drop_constraint("uq_account_identity", type_="unique")
