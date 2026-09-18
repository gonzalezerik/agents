"""Tests for luna/control_loop.py against a real Postgres instance
(`db_session` fixture) -- checkpoint persistence, resume-after-crash, and
failure handling all depend on actual row state, not just in-memory
behavior, so these are not mocked."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna import control_loop
from luna.control_loop import NODE_ORDER, RunContext
from luna.db.models import AgentRun, RunStatus


async def test_run_with_no_registered_nodes_completes_as_noop(db_session: AsyncSession) -> None:
    capability = f"test_noop_{uuid.uuid4().hex[:8]}"
    ctx = await control_loop.run(
        db_session, capability=capability, trigger_source="test", initial_data={"x": 1}
    )
    assert ctx.status == RunStatus.completed
    assert ctx.data == {"x": 1}

    row = await db_session.get(AgentRun, ctx.run_id)
    assert row is not None
    assert row.status == RunStatus.completed
    assert row.checkpoint_json["status"] == "completed"
    assert row.ended_at is not None


async def test_run_persists_checkpoint_after_each_node(db_session: AsyncSession) -> None:
    capability = f"test_checkpoint_{uuid.uuid4().hex[:8]}"
    seen_statuses: list[str] = []

    async def record_and_pass(ctx: RunContext) -> RunContext:
        seen_statuses.append(ctx.status.value)
        ctx.data["last_node"] = ctx.status.value
        return ctx

    for node in NODE_ORDER:
        control_loop.register_node(capability, node, record_and_pass)

    ctx = await control_loop.run(db_session, capability=capability, trigger_source="test")

    assert seen_statuses == [n.value for n in NODE_ORDER]
    assert ctx.data["last_node"] == RunStatus.respond.value
    assert ctx.status == RunStatus.completed


async def test_failed_node_marks_run_failed_and_records_error(db_session: AsyncSession) -> None:
    capability = f"test_fail_{uuid.uuid4().hex[:8]}"

    async def boom(ctx: RunContext) -> RunContext:
        raise ValueError("simulated capability bug")

    control_loop.register_node(capability, RunStatus.decide, boom)

    with pytest.raises(ValueError, match="simulated capability bug"):
        await control_loop.run(db_session, capability=capability, trigger_source="test")

    result = await db_session.execute(
        select(AgentRun).where(AgentRun.capability == capability)
    )
    row = result.scalar_one()
    assert row.status == RunStatus.failed
    assert "simulated capability bug" in row.checkpoint_json["error"]
    assert row.ended_at is not None


async def test_resume_continues_from_checkpointed_node(db_session: AsyncSession) -> None:
    capability = f"test_resume_{uuid.uuid4().hex[:8]}"
    ran_nodes: list[str] = []

    async def record(ctx: RunContext) -> RunContext:
        ran_nodes.append(ctx.status.value)
        return ctx

    # Only register nodes from "gate" onward -- "plan" and everything before
    # it should NOT run again on resume, proving resume picks up where the
    # checkpoint says, not from the beginning.
    for node in NODE_ORDER:
        if NODE_ORDER.index(node) >= NODE_ORDER.index(RunStatus.gate):
            control_loop.register_node(capability, node, record)

    # Simulate a crash: an agent_run left in "gate" status (i.e. "plan" just
    # completed, "gate" was about to run) with a checkpoint carrying data
    # from the earlier stages, but no run() call actually drove it there.
    run_row = AgentRun(
        capability=capability,
        trigger_source="test",
        status=RunStatus.gate,
        checkpoint_json={"data": {"from_plan": True}, "status": "gate", "error": None},
    )
    db_session.add(run_row)
    await db_session.flush()

    ctx = await control_loop.resume(db_session, run_row.id)

    assert ran_nodes == ["gate", "apply", "verify", "log", "respond"]
    assert ctx.status == RunStatus.completed
    assert ctx.data == {"from_plan": True}

    await db_session.refresh(run_row)
    assert run_row.status == RunStatus.completed


async def test_resume_on_already_terminal_run_is_a_noop(db_session: AsyncSession) -> None:
    capability = f"test_resume_terminal_{uuid.uuid4().hex[:8]}"
    run_row = AgentRun(
        capability=capability,
        trigger_source="test",
        status=RunStatus.completed,
        checkpoint_json={"data": {"done": True}, "status": "completed", "error": None},
    )
    db_session.add(run_row)
    await db_session.flush()

    ctx = await control_loop.resume(db_session, run_row.id)
    assert ctx.status == RunStatus.completed
    assert ctx.data == {"done": True}


async def test_resume_unknown_run_id_raises(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="no agent_run"):
        await control_loop.resume(db_session, uuid.uuid4())
