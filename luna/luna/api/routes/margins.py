"""`GET /margins`, `GET /budgets` -- read views over
`budget_watcher`'s (#5) sidecar history/config tables, for the dashboard.
Mounted by `luna/api/main.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.api.deps import get_db, require_service_token
from luna.db.models import Budget, MarginSnapshot

router = APIRouter(tags=["margins"], dependencies=[Depends(require_service_token)])


class MarginSnapshotOut(BaseModel):
    id: uuid.UUID
    ts: datetime
    component: str
    metric: str
    rolled_up_value: float

    model_config = {"from_attributes": True}


class BudgetOut(BaseModel):
    component: str
    metric: str
    limit_value: float
    updated_by: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.get("/margins", response_model=list[MarginSnapshotOut])
async def list_margins(
    component: str | None = None,
    metric: str | None = None,
    limit: int = Query(default=100, le=1000, ge=1),
    session: AsyncSession = Depends(get_db),
) -> list[MarginSnapshot]:
    stmt = select(MarginSnapshot).order_by(MarginSnapshot.ts.desc())
    if component is not None:
        stmt = stmt.where(MarginSnapshot.component == component)
    if metric is not None:
        stmt = stmt.where(MarginSnapshot.metric == metric)
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(
    component: str | None = None, session: AsyncSession = Depends(get_db)
) -> list[Budget]:
    stmt = select(Budget)
    if component is not None:
        stmt = stmt.where(Budget.component == component)
    result = await session.execute(stmt)
    return list(result.scalars().all())
