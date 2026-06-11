"""Financial interpretation layer.

Resolves each transaction's EFFECTIVE financial meaning — `financial_type`
(income/expense/transfer/adjustment/ignored) and `affects_reports` — separating
the raw bank fact (`Transaction.type`) from its managed P&L impact.

Precedence (highest first):
  1. manual override  (transaction.financial_type, with interpretation_locked)
  2. interpretation rule  (also stored on transaction.financial_type)
  3. category default  (category.default_financial_type)
  4. account-type baseline  (baseline_financial_type)
  5. raw `type` fallback

NULL on the transaction means "not overridden": reports resolve the effective
value at query time via COALESCE, so existing rows are correct without backfill.

SCOPE: this governs the P&L / report domain ONLY. Account balances, net worth and
running balances stay on the raw `type` + debt convention — they must NOT use
these helpers.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import case, func, select

from app.models.category import Category
from app.models.transaction import Transaction

INCOME = "income"
EXPENSE = "expense"
TRANSFER = "transfer"
ADJUSTMENT = "adjustment"
IGNORED = "ignored"

FINANCIAL_TYPES = (INCOME, EXPENSE, TRANSFER, ADJUSTMENT, IGNORED)
NEUTRAL_TYPES = (TRANSFER, ADJUSTMENT, IGNORED)  # excluded from P&L totals


# --------------------------------------------------------------------------- #
# Pure-Python resolution (recompute + serialization)
# --------------------------------------------------------------------------- #

def baseline_financial_type(account_type: Optional[str], raw_type: str) -> str:
    """Uniform baseline: `credit`=income, `debit`=expense, for EVERY account type
    (including credit cards). This preserves existing behavior with zero breakage.

    The credit-card sign problem is NOT solved here by guessing a per-account-type
    convention (that would break manually-entered card expenses, whose charge is a
    `debit`). Instead the data is normalized at IMPORT: a statement whose charges
    arrive as `credit` (e.g. Nubank CSV) is imported with the "invert values"
    option so charges land as `debit` (native convention). Categories/rules and
    per-transaction overrides refine the rest via the interpretation layer.

    `account_type` is kept in the signature so a future per-account convention can
    plug in here without touching call sites.
    """
    return INCOME if raw_type == "credit" else EXPENSE


def resolve_financial_type(
    *,
    tx_financial_type: Optional[str],
    category_default: Optional[str],
    account_type: Optional[str],
    raw_type: str,
) -> str:
    if tx_financial_type:
        return tx_financial_type
    if category_default:
        return category_default
    return baseline_financial_type(account_type, raw_type)


def default_affects_reports(financial_type: str) -> bool:
    return financial_type not in NEUTRAL_TYPES


def resolve_affects_reports(
    *,
    tx_affects_reports: Optional[bool],
    category_default_affects: Optional[bool],
    financial_type: str,
) -> bool:
    if tx_affects_reports is not None:
        return tx_affects_reports
    if category_default_affects is not None:
        return category_default_affects
    return default_affects_reports(financial_type)


# --------------------------------------------------------------------------- #
# Self-contained SQL expressions (drop-in; no JOIN requirement on the caller)
# --------------------------------------------------------------------------- #

def _cat_default_ar_sq():
    return (
        select(Category.default_affects_reports)
        .where(Category.id == Transaction.category_id)
        .correlate(Transaction)
        .scalar_subquery()
    )


def effective_financial_type_expr_for(financial_type_col, type_col, account_id_col, category_id_col):
    """Column-parameterized resolver — usable over a subquery's columns (e.g.
    the transactions-list summary) where the live `Transaction` isn't in scope.

    `account_id_col` is accepted for forward-compatibility with a possible
    per-account sign convention, but the current baseline is uniform and does
    not consult it.
    """
    cat_ft = (
        select(Category.default_financial_type)
        .where(Category.id == category_id_col)
        # Keep the inner Category in this subquery's FROM even when the outer
        # query already joins Category (e.g. spending_by_category); only the
        # category_id_col correlates outward.
        .correlate_except(Category)
        .scalar_subquery()
    )
    baseline = case(
        (type_col == "credit", INCOME),
        else_=EXPENSE,
    )
    return func.coalesce(financial_type_col, cat_ft, baseline)


def effective_financial_type_expr():
    """SQL: the resolved financial_type for a Transaction row (COALESCE precedence)."""
    return effective_financial_type_expr_for(
        Transaction.financial_type,
        Transaction.type,
        Transaction.account_id,
        Transaction.category_id,
    )


def is_income_expr():
    return effective_financial_type_expr() == INCOME


def is_expense_expr():
    return effective_financial_type_expr() == EXPENSE


def effective_affects_reports_expr():
    """SQL: resolved affects_reports (bool) for a Transaction row."""
    eft = effective_financial_type_expr()
    baseline_ar = case((eft.in_(NEUTRAL_TYPES), False), else_=True)
    return func.coalesce(
        Transaction.affects_reports,
        _cat_default_ar_sq(),
        baseline_ar,
    )
