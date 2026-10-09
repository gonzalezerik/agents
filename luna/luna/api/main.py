"""FastAPI app factory used by the `luna-api` entrypoint.

Mounts every route module under `luna/api/routes/`. `webhook.py` is
conditionally mounted since Jira webhook mode is an
opt-in alternative to the default polling path.

Migration policy: this module runs `alembic
upgrade head` once at `luna-api` process boot, in this factory's lifespan
handler, not via an initContainer.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import FastAPI

import luna.capabilities  # noqa: F401 - import registers every control_loop node
from luna.api.routes import (
    audit,
    health,
    ingest,
    margins,
    packages,
    proposals,
    rag,
    runs,
    webhook,
)
from luna.config import get_settings

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
    app.include_router(ingest.router)
    app.include_router(proposals.router)
    app.include_router(margins.router)
    app.include_router(rag.router)
    app.include_router(packages.router)
    if get_settings().jira_webhook_mode:
        app.include_router(webhook.router)

    return app


app = create_app()
