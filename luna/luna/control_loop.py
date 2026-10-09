"""The checkpointed control-loop state machine.

`Ingest -> Normalize -> Retrieve -> Decide -> Plan -> Gate -> Apply -> Verify
-> Log -> Respond`, implemented as a plain Python state machine, not a
framework. Each node is `async def node(ctx: RunContext) -> RunContext`.
`run()` drives the nodes in order, persisting `agent_run.checkpoint_json`
after every node so a crash mid-run resumes cleanly; `resume(run_id)` picks
up any `agent_run` left in a non-terminal state and continues from the node
recorded in its checkpoint.

## Node registry

This module never imports capability logic. Nodes are resolved through a
small runtime registry
(`register_node`) that capability modules are expected to populate at import
time (e.g. `control_loop.register_node("status_intake", RunStatus.decide,
my_decide_fn)`). Any node with nothing registered for a given
`(capability, node)` pair runs a **no-op pass-through** (returns `ctx`
unchanged) rather than raising -- this keeps `run()`/`resume()` fully
exercisable (and testable, `tests/test_control_loop.py`) on its own, at the
cost of silently "succeeding" through unimplemented stages if a capability
module forgets to register a node it needs -- which is why
`luna/capabilities/__init__.py` imports every capability for registration.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.db.models import NON_TERMINAL_RUN_STATUSES, AgentRun, RunStatus

NODE_ORDER: list[RunStatus] = [
    RunStatus.ingest,
    RunStatus.normalize,
    RunStatus.retrieve,
    RunStatus.decide,
    RunStatus.plan,
    RunStatus.gate,
    RunStatus.apply,
    RunStatus.verify,
    RunStatus.log,
    RunStatus.respond,
]

TERMINAL_STATUSES = frozenset({RunStatus.completed, RunStatus.failed, RunStatus.cancelled})


@dataclass
class RunContext:
    """The value threaded through every node. `data` is a freeform,
    JSON-serializable payload -- this is deliberately not a fixed schema
    because each capability's Ingest/Normalize/... stages carry different
    shaped state (a Discord message vs a Jira poll batch vs a transcript
    segment); the checkpoint contract only requires that whatever a node
    puts in `data` round-trips through JSON, since it's persisted verbatim
    into `agent_run.checkpoint_json`."""

    run_id: uuid.UUID
    capability: str
    trigger_source: str
    actor_user: str | None = None
    status: RunStatus = RunStatus.ingest
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


NodeFn = Callable[[RunContext], Awaitable[RunContext]]

_REGISTRY: dict[str, dict[RunStatus, NodeFn]] = {}


def register_node(capability: str, node: RunStatus, fn: NodeFn) -> None:
    """Capability modules call this at import time to plug their node
    implementations into the shared state machine. Re-registering the same
    (capability, node) pair overwrites the previous registration (last
    import wins) -- intended for test fixtures overriding a node, not for
    normal operation."""
    _REGISTRY.setdefault(capability, {})[node] = fn


def registered_nodes(capability: str) -> frozenset[RunStatus]:
    return frozenset(_REGISTRY.get(capability, {}).keys())


async def _noop(ctx: RunContext) -> RunContext:
    return ctx


def _checkpoint_payload(ctx: RunContext) -> dict[str, Any]:
    return {
        "data": ctx.data,
        "status": ctx.status.value,
        "error": ctx.error,
        "trigger_source": ctx.trigger_source,
        "actor_user": ctx.actor_user,
    }


async def _persist(session: AsyncSession, run_row: AgentRun, ctx: RunContext) -> None:
    run_row.status = ctx.status
    run_row.checkpoint_json = _checkpoint_payload(ctx)
    if ctx.status in TERMINAL_STATUSES:
        from datetime import datetime

        run_row.ended_at = datetime.now()
    await session.flush()


async def _drive(session: AsyncSession, run_row: AgentRun, ctx: RunContext, start_index: int) -> RunContext:
    for i in range(start_index, len(NODE_ORDER)):
        node = NODE_ORDER[i]
        ctx.status = node
        node_fn = _REGISTRY.get(ctx.capability, {}).get(node, _noop)
        try:
            ctx = await node_fn(ctx)
        except Exception as exc:  # noqa: BLE001 - deliberately broad: any node failure halts the run
            ctx.status = RunStatus.failed
            ctx.error = f"{node.value}: {exc}"
            await _persist(session, run_row, ctx)
            raise

        is_last = i == len(NODE_ORDER) - 1
        ctx.status = RunStatus.completed if is_last else NODE_ORDER[i + 1]
        await _persist(session, run_row, ctx)

    return ctx


async def run(
    session: AsyncSession,
    *,
    capability: str,
    trigger_source: str,
    actor_user: str | None = None,
    initial_data: dict[str, Any] | None = None,
) -> RunContext:
    """Start a brand-new run and drive it to completion (or first failure)."""
    run_row = AgentRun(
        capability=capability,
        trigger_source=trigger_source,
        actor_user=actor_user,
        status=RunStatus.ingest,
        checkpoint_json={},
    )
    session.add(run_row)
    await session.flush()  # assigns run_row.id

    ctx = RunContext(
        run_id=run_row.id,
        capability=capability,
        trigger_source=trigger_source,
        actor_user=actor_user,
        status=RunStatus.ingest,
        data=initial_data or {},
    )
    return await _drive(session, run_row, ctx, start_index=0)


async def resume(session: AsyncSession, run_id: uuid.UUID) -> RunContext:
    """Resume any `agent_run` left in a non-terminal state, continuing from
    the node recorded in its checkpoint. `workers/poller.py` and the API's
    proposal-confirm handler both call this on startup for every non-terminal
    run."""
    result = await session.execute(select(AgentRun).where(AgentRun.id == run_id))
    run_row = result.scalar_one_or_none()
    if run_row is None:
        raise ValueError(f"no agent_run with id={run_id}")

    if run_row.status not in NON_TERMINAL_RUN_STATUSES:
        # Already terminal -- nothing to resume. Return the checkpoint as-is
        # rather than raising, so callers can treat resume() as idempotent
        # (e.g. a worker restart re-scanning all non-terminal runs and
        # racing a run that just finished).
        checkpoint = run_row.checkpoint_json or {}
        return RunContext(
            run_id=run_row.id,
            capability=run_row.capability,
            trigger_source=run_row.trigger_source,
            actor_user=run_row.actor_user,
            status=run_row.status,
            data=checkpoint.get("data", {}),
            error=checkpoint.get("error"),
        )

    checkpoint = run_row.checkpoint_json or {}
    ctx = RunContext(
        run_id=run_row.id,
        capability=run_row.capability,
        trigger_source=run_row.trigger_source,
        actor_user=run_row.actor_user,
        status=run_row.status,
        data=checkpoint.get("data", {}),
        error=checkpoint.get("error"),
    )
    start_index = NODE_ORDER.index(run_row.status)
    return await _drive(session, run_row, ctx, start_index=start_index)
