"""financial interpretation layer: financial_type/affects_reports + rule kind

Revision ID: 060
Revises: 059
Create Date: 2026-06-10

Purely additive. Adds a derived "financial interpretation" layer that separates
the raw bank fact (transaction.type) from its managed P&L impact:

- transactions.financial_type (income|expense|transfer|adjustment|ignored, NULL)
- transactions.affects_reports (bool, NULL)
- transactions.interpretation_locked (bool, default false) — set when a user
  manually overrides; protects the override from automatic recompute.
- categories.default_financial_type / default_affects_reports (NULL) — let a
  category carry default interpretation behaviour.
- rules.kind ('categorization' | 'interpretation', default 'categorization') —
  the same rules table now also holds interpretation rules.

NULL financial_type/affects_reports means "not overridden": reports resolve the
effective value at query time via COALESCE(tx -> category default -> account-type
baseline), so existing rows are already correct without any backfill.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "060"
down_revision: Union[str, None] = "059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("financial_type", sa.String(length=20), nullable=True))
    op.add_column("transactions", sa.Column("affects_reports", sa.Boolean(), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("interpretation_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_transactions_financial_type", "transactions", ["financial_type"])

    op.add_column("categories", sa.Column("default_financial_type", sa.String(length=20), nullable=True))
    op.add_column("categories", sa.Column("default_affects_reports", sa.Boolean(), nullable=True))

    op.add_column(
        "rules",
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="categorization"),
    )


def downgrade() -> None:
    op.drop_column("rules", "kind")
    op.drop_column("categories", "default_affects_reports")
    op.drop_column("categories", "default_financial_type")
    op.drop_index("ix_transactions_financial_type", table_name="transactions")
    op.drop_column("transactions", "interpretation_locked")
    op.drop_column("transactions", "affects_reports")
    op.drop_column("transactions", "financial_type")
