"""`GET /healthz` -- no auth, no DB/LLM check.

Used by k8s liveness probes. Must work even if the DB or LLM endpoint is
down; that's what a separate `/readyz` (not implemented) would be for.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
