"""Budget forecasting from historical transactions.

Sums real expenses per category over a chosen period and proposes budget
amounts (monthly average or period total), then materializes them as budgets
for a target month.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.schemas.budget import BudgetForecastItem, BudgetFromForecastItem
from app.services._query_filters import counts_as_user_pnl


def _primary_amount_expr():
    """Amount in primary currency: amount_primary when available, else amount."""
    return func.coalesce(Transaction.amount_primary, Transaction.amount)


def _month_count(from_date: date, to_date: date) -> int:
    """Inclusive month span, e.g. Apr 1 → May 31 = 2."""
    months = (to_date.year - from_date.year) * 12 + (to_date.month - from_date.month) + 1
    return max(1, months)


async def forecast_from_transactions(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    from_date: date,
    to_date: date,
    strategy: str = "average",
) -> list[BudgetForecastItem]:
    """Sum expenses per category in [from_date, to_date] and suggest a budget.

    strategy="average" -> total / month_count; strategy="total" -> total.
    Uses Transaction.date (not effective_date) for predictability over the
    selected window, mirrors budget reporting with counts_as_user_pnl() and
    amount_primary for multi-currency."""
    months = _month_count(from_date, to_date)

    rows = (await session.execute(
        select(Category.id, Category.name, func.sum(_primary_amount_expr()))
        .join(Transaction, Transaction.category_id == Category.id)
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.date >= from_date,
            Transaction.date <= to_date,
            counts_as_user_pnl(),
        )
        .group_by(Category.id, Category.name)
    )).all()

    items: list[BudgetForecastItem] = []
    for cat_id, cat_name, total in rows:
        total_abs = abs(total or Decimal("0"))
        if total_abs == 0:
            continue
        suggested = (total_abs / months) if strategy == "average" else total_abs
        suggested = suggested.quantize(Decimal("0.01"))
        items.append(BudgetForecastItem(
            category_id=cat_id, category_name=cat_name,
            total=total_abs, months=months, suggested_amount=suggested,
        ))
    items.sort(key=lambda i: float(i.total), reverse=True)
    return items


async def apply_forecast(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    month: date,
    is_recurring: bool,
    items: list[BudgetFromForecastItem],
) -> tuple[int, int]:
    """Create/update budgets for the target month from forecast items.

    Targets the EXACT (month, is_recurring) rows so updates never mutate a
    recurring default from another month. Returns (created, updated)."""
    month_start = month.replace(day=1)
    existing = (await session.execute(
        select(Budget).where(
            Budget.workspace_id == workspace_id,
            Budget.month == month_start,
            Budget.is_recurring == is_recurring,
        )
    )).scalars().all()
    by_cat = {b.category_id: b for b in existing}

    created = 0
    updated = 0
    for item in items:
        budget = by_cat.get(item.category_id)
        if budget is not None:
            budget.amount = item.amount
            updated += 1
        else:
            session.add(Budget(
                user_id=user_id,
                workspace_id=workspace_id,
                category_id=item.category_id,
                amount=item.amount,
                month=month_start,
                is_recurring=is_recurring,
            ))
            created += 1
    await session.commit()
    return created, updated
