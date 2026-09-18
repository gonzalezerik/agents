"""FastAPI app factory used by the `luna-api` entrypoint.

Only mounts the routers this build owns (`health`, `runs`, `audit`) --
CONTRACT.md scopes `ingest.py`, `proposals.py`, `margins.py`, `rag.py`,
`packages.py`, `webhook.py` under `luna/api/routes/` to other builders. When
those land, add `app.include_router(...)` calls for them here alongside the
existing ones; nothing about this factory needs to change structurally.

Migration policy (CONTRACT.md: "pick one [initContainer or boot-time
upgrade], don't do both, note it in README"): this build runs `alembic
upgrade head` once at `luna-api` process boot, in this factory's lifespan
handler, not via an initContainer -- noted here and in NOTES.md since this
build doesn't own README.md.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from luna.api.routes import audit, health, runs

logger = logging.getLogger("luna.api")


def _run_migrations() -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        _run_migrations()
    except Exception:
        logger.exception(
            "alembic upgrade head failed at luna-api boot -- refusing to serve "
            "traffic against a possibly-stale schema"
        )
        raise
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="LUNA API", lifespan=lifespan)

    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(audit.router)

    return app


app = create_app()
