"""add categorization columns and category_rule

Revision ID: 208f30aad50f
Revises: 6518b8bf3cfe
Create Date: 2026-09-08

build-plan #8, Part 1. The layered, non-destructive category model (REQ-CAT-002/
003/004):

- `transaction.merchant_normalized` -- the cleaned merchant rules and the LLM
  both operate on.
- `transaction.predicted_category` / `predicted_confidence` / `predicted_source`
  -- the automated guess, kept even after an override.
- `transaction.user_category` -- a per-transaction override.
- `transaction.category` is promoted from nullable to NOT NULL (default
  `Uncategorized`) -- it is now the materialized *effective* category -- and
  `transaction.category_source` records how it was decided.
- new `category_rule` table -- a user's "always categorize [merchant] as X".

SQLite can't add a CHECK constraint or change a column's nullability in place, so
`transaction` goes through `batch_alter_table` (a full rebuild). Pre-existing
rows get their NULL `category` backfilled first. FK enforcement is turned off
around the rebuild because `transaction` has a self-referential FK
(`duplicate_of_id`) and the `DROP TABLE` step trips enforcement on a populated
database (same as migration 6518b8bf3cfe).
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "208f30aad50f"
down_revision: str | Sequence[str] | None = "6518b8bf3cfe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of app.models.taxonomy.CATEGORIES at the time of this migration.
_CATEGORIES = (
    "Income",
    "Transfers",
    "Credit Card Payments",
    "Housing",
    "Utilities",
    "Groceries",
    "Dining",
    "Transportation",
    "Fuel",
    "Shopping",
    "Entertainment",
    "Subscriptions",
    "Healthcare",
    "Insurance",
    "Education",
    "Travel",
    "Personal Care",
    "Fees & Interest",
    "Cash & ATM",
    "Taxes",
    "Debt Payments",
    "Uncategorized",
)
_CATEGORY_LIST = ", ".join(f"'{c}'" for c in _CATEGORIES)
_PREDICTED_SOURCES = "'RULE', 'LLM', 'NONE'"
_CATEGORY_SOURCES = "'USER', 'MERCHANT_RULE', 'RULE', 'LLM', 'NONE'"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA foreign_keys=OFF")

    op.create_table(
        "category_rule",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("merchant", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant"),
        sa.CheckConstraint(
            f"category IN ({_CATEGORY_LIST})", name="ck_category_rule_category"
        ),
    )
    op.create_index(
        op.f("ix_category_rule_merchant"), "category_rule", ["merchant"], unique=True
    )

    # Backfill before the rebuild makes `category` NOT NULL.
    op.execute(
        "UPDATE \"transaction\" SET category = 'Uncategorized' WHERE category IS NULL"
    )

    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "merchant_normalized",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "predicted_category",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("predicted_confidence", sa.Float(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "predicted_source",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="NONE",
            )
        )
        batch_op.add_column(
            sa.Column(
                "user_category",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "category_source",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="NONE",
            )
        )
        batch_op.alter_column(
            "category",
            existing_type=sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="Uncategorized",
        )
        batch_op.create_index(
            batch_op.f("ix_transaction_merchant_normalized"),
            ["merchant_normalized"],
            unique=False,
        )
        batch_op.create_check_constraint(
            "ck_transaction_category", f"category IN ({_CATEGORY_LIST})"
        )
        batch_op.create_check_constraint(
            "ck_transaction_predicted_category",
            f"predicted_category IS NULL OR predicted_category IN ({_CATEGORY_LIST})",
        )
        batch_op.create_check_constraint(
            "ck_transaction_user_category",
            f"user_category IS NULL OR user_category IN ({_CATEGORY_LIST})",
        )
        batch_op.create_check_constraint(
            "ck_transaction_predicted_source",
            f"predicted_source IN ({_PREDICTED_SOURCES})",
        )
        batch_op.create_check_constraint(
            "ck_transaction_category_source",
            f"category_source IN ({_CATEGORY_SOURCES})",
        )

    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.drop_constraint("ck_transaction_category_source", type_="check")
        batch_op.drop_constraint("ck_transaction_predicted_source", type_="check")
        batch_op.drop_constraint("ck_transaction_user_category", type_="check")
        batch_op.drop_constraint("ck_transaction_predicted_category", type_="check")
        batch_op.drop_constraint("ck_transaction_category", type_="check")
        batch_op.drop_index(batch_op.f("ix_transaction_merchant_normalized"))
        batch_op.alter_column(
            "category",
            existing_type=sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            server_default=None,
        )
        batch_op.drop_column("category_source")
        batch_op.drop_column("user_category")
        batch_op.drop_column("predicted_source")
        batch_op.drop_column("predicted_confidence")
        batch_op.drop_column("predicted_category")
        batch_op.drop_column("merchant_normalized")

    op.drop_index(op.f("ix_category_rule_merchant"), table_name="category_rule")
    op.drop_table("category_rule")

    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA foreign_keys=ON")
