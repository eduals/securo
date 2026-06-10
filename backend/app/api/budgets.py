import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import (
    WorkspaceContext,
    current_workspace,
    current_writable_workspace,
)
from app.schemas.budget import (
    BudgetCreate,
    BudgetForecastResponse,
    BudgetFromForecastRequest,
    BudgetFromForecastResult,
    BudgetRead,
    BudgetUpdate,
    BudgetVsActual,
)
from app.services import budget_forecast_service, budget_service

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("", response_model=list[BudgetRead])
async def list_budgets(
    month: Optional[date] = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await budget_service.get_budgets(session, ctx.workspace.id, month)


@router.post("", response_model=BudgetRead, status_code=status.HTTP_201_CREATED)
async def create_budget(
    data: BudgetCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await budget_service.create_budget(session, ctx.workspace.id, ctx.user_id, data)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{budget_id}", response_model=BudgetRead)
async def update_budget(
    budget_id: uuid.UUID,
    data: BudgetUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    budget = await budget_service.update_budget(session, budget_id, ctx.workspace.id, data)
    if not budget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return budget


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(
    budget_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    deleted = await budget_service.delete_budget(session, budget_id, ctx.workspace.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")


@router.get("/comparison", response_model=list[BudgetVsActual])
async def budget_comparison(
    month: Optional[date] = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await budget_service.get_budget_vs_actual(session, ctx.workspace.id, ctx.user_id, month)


@router.get("/forecast", response_model=BudgetForecastResponse)
async def budget_forecast(
    from_date: date = Query(...),
    to_date: date = Query(...),
    strategy: str = Query("average"),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Suggest budget amounts per category from expenses in [from_date, to_date]."""
    items = await budget_forecast_service.forecast_from_transactions(
        session, ctx.workspace.id, from_date, to_date, strategy
    )
    return BudgetForecastResponse(from_date=from_date, to_date=to_date, strategy=strategy, items=items)


@router.post("/from-forecast", response_model=BudgetFromForecastResult)
async def apply_forecast(
    payload: BudgetFromForecastRequest,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Create/update budgets for the target month from forecast items."""
    created, updated = await budget_forecast_service.apply_forecast(
        session, ctx.workspace.id, ctx.user_id,
        payload.month, payload.is_recurring, payload.items,
    )
    return BudgetFromForecastResult(created=created, updated=updated)
