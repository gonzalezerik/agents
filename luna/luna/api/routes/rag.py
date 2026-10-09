"""`POST /rag/query`.

Defines an `APIRouter` named `router`; `luna/api/main.py` mounts it with
`app.include_router(rag.router)`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from luna.api.deps import get_db, require_service_token
from luna.capabilities.rag_qna import answer_question
from luna.db.models import AgentRun, RunStatus
from luna.decision.engine import get_decision_provider
from luna.generation.generator import Generation

router = APIRouter(tags=["rag"], dependencies=[Depends(require_service_token)])


class RagQueryIn(BaseModel):
    question: str


class RagQueryOut(BaseModel):
    answer: str
    citations: list[str]
    sufficient: bool


@router.post("/rag/query", response_model=RagQueryOut)
async def rag_query(body: RagQueryIn, session: AsyncSession = Depends(get_db)) -> RagQueryOut:
    run = AgentRun(capability="rag_qna", trigger_source="api", status=RunStatus.decide)
    session.add(run)
    await session.flush()

    provider = get_decision_provider()
    generation = Generation.from_settings()
    try:
        result = await answer_question(session, run.id, provider, generation, body.question)
    finally:
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await aclose()
        await generation.aclose()

    run.status = RunStatus.completed
    await session.commit()

    return RagQueryOut(answer=result.answer, citations=result.citations, sufficient=result.sufficient)
