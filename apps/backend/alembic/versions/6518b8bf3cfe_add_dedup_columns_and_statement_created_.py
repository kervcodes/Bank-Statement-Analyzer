"""add dedup columns and statement created_at

Revision ID: 6518b8bf3cfe
Revises: 69a3cd180f72
Create Date: 2026-09-08 13:27:37.150756

build-plan #7. `dedup_status` + `duplicate_of_id` on `statement` and `transaction`
(REQ-DEDUP-003), a nullable `transaction.reference_id` (REQ-DEDUP-002, not
populated yet), and `statement.created_at` so dedup can pick the older statement
as canonical.

SQLite can't ALTER a table to add a constraint or a self-referential foreign key
in place, so both tables go through `batch_alter_table`, which rebuilds them.
`server_default` covers any pre-existing rows; the models set the value for new
rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6518b8bf3cfe"
down_revision: str | Sequence[str] | None = "69a3cd180f72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEDUP_CHECK = "dedup_status IN ('UNIQUE', 'DUPLICATE', 'POSSIBLE_DUPLICATE')"


def upgrade() -> None:
    """Upgrade schema."""
    # `transaction` and `statement_job` have FKs to `statement`, so the batch
    # rebuild's `DROP TABLE statement` trips FK enforcement on a populated
    # database. Alembic uses non-transactional DDL for SQLite, so this PRAGMA
    # takes effect; the ids are preserved through the copy, so the FKs are still
    # valid once re-enabled.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table("statement", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "dedup_status",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="UNIQUE",
            )
        )
        batch_op.add_column(
            sa.Column(
                "duplicate_of_id",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_statement_duplicate_of_id"),
            ["duplicate_of_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_statement_duplicate_of_id_statement",
            "statement",
            ["duplicate_of_id"],
            ["id"],
        )
        batch_op.create_check_constraint("ck_statement_dedup_status", _DEDUP_CHECK)

    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "reference_id",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "dedup_status",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="UNIQUE",
            )
        )
        batch_op.add_column(
            sa.Column(
                "duplicate_of_id",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_transaction_duplicate_of_id"),
            ["duplicate_of_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_transaction_duplicate_of_id_transaction",
            "transaction",
            ["duplicate_of_id"],
            ["id"],
        )
        batch_op.create_check_constraint("ck_transaction_dedup_status", _DEDUP_CHECK)

    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.drop_constraint("ck_transaction_dedup_status", type_="check")
        batch_op.drop_constraint(
            "fk_transaction_duplicate_of_id_transaction", type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_transaction_duplicate_of_id"))
        batch_op.drop_column("duplicate_of_id")
        batch_op.drop_column("dedup_status")
        batch_op.drop_column("reference_id")

    with op.batch_alter_table("statement", schema=None) as batch_op:
        batch_op.drop_constraint("ck_statement_dedup_status", type_="check")
        batch_op.drop_constraint(
            "fk_statement_duplicate_of_id_statement", type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_statement_duplicate_of_id"))
        batch_op.drop_column("duplicate_of_id")
        batch_op.drop_column("dedup_status")
        batch_op.drop_column("created_at")
