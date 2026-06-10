import uuid
from datetime import date as _Date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class BudgetCreate(BaseModel):
    category_id: uuid.UUID
    amount: Decimal
    month: _Date  # First day of month
    is_recurring: bool = False


class BudgetUpdate(BaseModel):
    amount: Optional[Decimal] = None
    effective_month: Optional[_Date] = None


class BudgetRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    category_id: uuid.UUID
    amount: Decimal
    month: _Date
    is_recurring: bool

    model_config = ConfigDict(from_attributes=True)


class BudgetVsActual(BaseModel):
    category_id: uuid.UUID
    category_name: str
    category_icon: str
    category_color: str
    group_id: Optional[uuid.UUID] = None
    group_name: Optional[str] = None
    budget_amount: Optional[Decimal] = None
    actual_amount: Decimal
    prev_month_amount: Decimal = Decimal("0")
    percentage_used: Optional[float] = None
    is_recurring: bool = False


class BudgetForecastItem(BaseModel):
    category_id: uuid.UUID
    category_name: str
    total: Decimal           # summed expenses in the period (primary currency)
    months: int              # number of months covered by the period
    suggested_amount: Decimal  # total/months (average) or total, per strategy


class BudgetForecastResponse(BaseModel):
    from_date: _Date
    to_date: _Date
    strategy: str
    items: list[BudgetForecastItem]


class BudgetFromForecastItem(BaseModel):
    category_id: uuid.UUID
    amount: Decimal


class BudgetFromForecastRequest(BaseModel):
    month: _Date              # target month (any day; normalized to day 1)
    is_recurring: bool = False
    items: list[BudgetFromForecastItem]


class BudgetFromForecastResult(BaseModel):
    created: int
    updated: int
