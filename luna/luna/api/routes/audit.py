"""`GET /audit?...` (CONTRACT.md API surface) -- read + verify the
hash-chained audit log for the dashboard's AI-quality review view."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.api.deps import get_db, require_service_token
from luna.audit import ChainVerificationResult, verify_chain
from luna.db.models import AuditEvent

router = APIRouter(tags=["audit"], dependencies=[Depends(require_service_token)])


class AuditEventOut(BaseModel):
    id: int
    run_id: uuid.UUID | None
    ts: datetime
    actor: str
    action: str
    prompt_ref: str | None
    tool_call_json: dict[str, Any] | None
    result_ref: str | None
    hash_prev: str | None
    hash_self: str

    model_config = {"from_attributes": True}


class AuditListOut(BaseModel):
    events: list[AuditEventOut]
    verification: ChainVerificationResultOut | None = None


class ChainVerificationResultOut(BaseModel):
    ok: bool
    rows_checked: int
    first_broken_id: int | None
    reason: str | None

    @classmethod
    def from_result(cls, result: ChainVerificationResult) -> ChainVerificationResultOut:
        return cls(
            ok=result.ok,
            rows_checked=result.rows_checked,
            first_broken_id=result.first_broken_id,
            reason=result.reason,
        )


AuditListOut.model_rebuild()


@router.get("/audit", response_model=AuditListOut)
async def list_audit(
    run_id: uuid.UUID | None = None,
    actor: str | None = None,
    limit: int = Query(default=100, le=1000, ge=1),
    offset: int = Query(default=0, ge=0),
    verify: bool = False,
    session: AsyncSession = Depends(get_db),
) -> AuditListOut:
    stmt = select(AuditEvent).order_by(AuditEvent.id.asc())
    if run_id is not None:
        stmt = stmt.where(AuditEvent.run_id == run_id)
    if actor is not None:
        stmt = stmt.where(AuditEvent.actor == actor)
    stmt = stmt.offset(offset).limit(limit)

    result = await session.execute(stmt)
    events = [AuditEventOut.model_validate(row) for row in result.scalars().all()]

    verification_out = None
    if verify:
        verification = await verify_chain(session, run_id=run_id)
        verification_out = ChainVerificationResultOut.from_result(verification)

    return AuditListOut(events=events, verification=verification_out)
