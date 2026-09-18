"""Shared pytest fixtures.

Two live-infrastructure dependencies are used for real in this suite, each
with its own graceful-skip story so the plain `pytest` run stays usable with
no cluster access (CONTRACT.md):

- The local LLM endpoint (`LLM_BASE_URL`) -- tests marked `@pytest.mark.llm`
  are skipped automatically if it's unreachable at collection time (checked
  once, synchronously, against `GET /models`).
- Postgres -- `db_session` tries to connect to `TEST_DATABASE_URL` (falls
  back to `DATABASE_URL`, then to the ephemeral local instance this build
  was developed/tested against) and skips any test that needs it if no
  server answers. This is not one of CONTRACT.md's explicitly-named "must
  run with no live services" externals (Jira/Discord/Slack/LLM), but the
  same skip-don't-fail discipline applies for the same reason: a clean
  checkout with no Postgres reachable should not turn into a wall of
  errors.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from luna.config import get_settings
from luna.db.models import Base

TEST_DATABASE_URL = (
    os.environ.get("TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql+asyncpg://luna@127.0.0.1:55432/luna"
)


def _llm_reachable() -> bool:
    settings = get_settings()
    try:
        resp = httpx.get(
            f"{settings.llm_base_url}/models",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=5.0,
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _llm_reachable():
        return
    skip_llm = pytest.mark.skip(reason=f"LLM_BASE_URL unreachable: {get_settings().llm_base_url}")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip_llm)


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    # Function-scoped (not session-scoped) deliberately: pytest-asyncio's
    # default fixture loop scope is per-test-function, and an asyncpg
    # connection pool is bound to the event loop it was created on -- a
    # session-scoped engine here would work for the first test and then
    # raise "another operation is in progress" (or similar) on every test
    # after, because it would try to reuse loop-bound connections from a
    # now-closed loop. Recreating the engine per test costs a little time
    # but sidesteps that whole class of flaky cross-loop bug.
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.run_sync(lambda c: None)
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"no reachable Postgres at {TEST_DATABASE_URL}: {exc}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
        await session.rollback()

    # Per-test isolation: truncate everything so tests don't see each
    # other's rows. CASCADE handles FK ordering without needing to compute
    # a topological sort of Base.metadata.sorted_tables by hand.
    async with db_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest.fixture
def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture(autouse=True)
async def _reset_global_db_engine() -> AsyncIterator[None]:
    """`luna/db/session.py`'s `get_engine()`/`session_scope()` cache one
    module-level `AsyncEngine` for the whole process -- correct and desired
    in production (`luna-api`/`luna-worker` run one event loop for their
    entire lifetime), but a real bug across this test suite: pytest-asyncio
    gives each test function its own fresh event loop by default, and an
    asyncpg connection pool is bound to the loop it was created on (see
    `db_engine`'s own docstring above for the same class of issue in this
    file's dedicated test engine). Every capability's control-loop `decide`
    node opens its own session via `session_scope()` (not the injected
    `db_session` fixture, since production code has no FastAPI dependency
    injection to lean on there) -- so whichever test runs first binds the
    global engine to its loop, and every later test that also reaches
    `session_scope()` gets `RuntimeError: Event loop is closed` /
    `Future ... attached to a different loop`, unpredictably, depending on
    test order. Found while merging the Jira, chat, and knowledge layers
    together, once tests from all three started actually exercising
    `session_scope()` in the same pytest run. Fixed by disposing the global
    engine both before and after every test, forcing a fresh one bound to
    that test's own loop on next use."""
    from luna.db.session import dispose_engine

    await dispose_engine()
    yield
    await dispose_engine()
