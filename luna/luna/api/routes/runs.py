"""`GET /runs/{id}` (CONTRACT.md API surface)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from luna.api.deps import get_db, require_service_token
from luna.db.models import AgentRun

router = APIRouter(tags=["runs"], dependencies=[Depends(require_service_token)])


class RunOut(BaseModel):
    id: uuid.UUID
    capability: str
    trigger_source: str
    actor_user: str | None
    started_at: datetime
    ended_at: datetime | None
    status: str
    checkpoint_json: dict[str, Any]

    model_config = {"from_attributes": True}


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> AgentRun:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run
