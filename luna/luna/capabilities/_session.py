"""Contextvar plumbing so capability node functions can reach the
`AsyncSession` a run is using, without changing `control_loop.py`.

## Why this exists

`control_loop.NodeFn = Callable[[RunContext], Awaitable[RunContext]]` --
nodes only receive the `RunContext`, never the `AsyncSession` that
`control_loop.run()`/`resume()` were called with. But every real node this
package implements needs a session: `decision.engine.decide_many()` writes a
`decision_call` row, Plan/Apply write `Proposal`/`JiraChange` rows, and
`JiraAdapter`'s write methods check `Proposal` state for idempotency.
`RunContext.data` can't carry the session either -- it's persisted verbatim
into `agent_run.checkpoint_json` (JSONB), so it must stay JSON-serializable.

`control_loop.py` is foundational, already-tested, out of this package's
scope to modify. So: every caller of `control_loop.run()`/`resume()`
anywhere a status_intake/blocker_dependency/budget_watcher/deadline_reminders
node might run -- `status_intake.start()` (the ingest-triggering entrypoint),
`workers/poller.py`, `workers/scheduler.py`, and the
`api/routes/proposals.py` confirm handler -- must go through
`run_with_session`/`resume_with_session` below instead of calling
`control_loop.run`/`resume` directly. That sets a `ContextVar` for the
duration of the drive; node functions read it back via `current_session()`.

This is safe specifically because `control_loop._drive` awaits each node in
sequence within a single `asyncio` task (never spawns concurrent sibling
tasks per node) -- a `ContextVar` set in a task is visible to everything
awaited from within that same task, and is never visible to a different,
concurrently-running task's own context. Two runs driven concurrently (e.g.
two poller ticks as separate tasks) each get their own copy.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from luna import control_loop
from luna.control_loop import RunContext

_CURRENT_SESSION: ContextVar[AsyncSession] = ContextVar("luna_capability_current_session")


@asynccontextmanager
async def bound_session(session: AsyncSession) -> AsyncIterator[None]:
    """Bind `session` as `current_session()` for the duration of the `with`
    block. Used by `status_intake.start()`, which drives nodes itself
    (ingest..gate) rather than through `control_loop.run()` -- see that
    module's docstring for why."""
    token = _CURRENT_SESSION.set(session)
    try:
        yield
    finally:
        _CURRENT_SESSION.reset(token)


def current_session() -> AsyncSession:
    """The `AsyncSession` bound to the run currently being driven. Raises a
    clear `RuntimeError` (not `LookupError`) if called outside of
    `run_with_session`/`resume_with_session` -- e.g. a node function called
    directly in a unit test without going through either wrapper."""
    try:
        return _CURRENT_SESSION.get()
    except LookupError as exc:
        raise RuntimeError(
            "No AsyncSession bound to this control_loop run. Capability node "
            "functions must be driven via capabilities._session.run_with_session()/"
            "resume_with_session(), not control_loop.run()/resume() directly."
        ) from exc


async def run_with_session(session: AsyncSession, **kwargs: Any) -> RunContext:
    """Drive a brand-new run, binding `session` for every node's duration."""
    async with bound_session(session):
        return await control_loop.run(session, **kwargs)


async def resume_with_session(session: AsyncSession, run_id: uuid.UUID) -> RunContext:
    """Resume a checkpointed run, binding `session` for every node's duration."""
    async with bound_session(session):
        return await control_loop.resume(session, run_id)
