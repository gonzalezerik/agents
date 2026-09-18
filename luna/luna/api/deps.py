"""Shared FastAPI dependencies: DB session + bearer-token auth.

CONTRACT.md: "Auth on every route except `/healthz`: a shared-secret bearer
token (`INTERNAL_SERVICE_TOKEN` env, checked in `api/deps.py`) since
`luna-discord` and `luna-slack` are the only callers of `/ingest/*`, and
there is no end-user-facing web UI in v1."
"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from luna.config import Settings, get_settings
from luna.db.session import get_session_factory

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def require_service_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Every route except `/healthz` depends on this. Fails loudly and
    specifically per CONTRACT.md's credential-handling policy: an unset
    `INTERNAL_SERVICE_TOKEN` is a server misconfiguration (500, with a clear
    log line), not something that should silently accept any bearer value or
    silently no-op auth -- distinct from a caller simply presenting a wrong
    or missing token (401)."""
    if not settings.internal_service_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Server misconfiguration: INTERNAL_SERVICE_TOKEN is not set. "
                "Set it in the luna-api deployment's env/secret before any "
                "authenticated route can be used."
            ),
        )
    if credentials is None or not hmac.compare_digest(
        credentials.credentials, settings.internal_service_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid bearer token",
        )
