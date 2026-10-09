"""Tests for `luna/workers/poller.py`.

Covers "the poller detects an externally-made change within one interval"
by simulating an issue that
changed outside of LUNA and asserting `poll_once()`'s interval JQL surfaces
it, and the resume-on-startup carve-out for `status_intake` runs parked at
`apply` (must not resume a run whose proposal is still merely pending, but
must resume one whose proposal was already confirmed -- see
`poller.py`/`status_intake.py`'s module docstrings for why).
"""

from __future__ import annotations

from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from luna.capabilities import blocker_dependency, budget_watcher
from luna.control_loop import RunContext
from luna.db import session as db_session_module
from luna.db.models import AgentRun, Proposal, ProposalStatus, RunStatus
from luna.workers import poller


@pytest_asyncio.fixture(autouse=True)
async def _fresh_global_engine():
    """`poller.resume_pending_runs`/`poll_once` use `db.session.session_scope()`,
    which is a module-level singleton engine (by design -- it's shared across
    every process, see `db/session.py`'s docstring). `tests/conftest.py`'s
    own `db_engine` fixture is function-scoped specifically because an
    asyncpg connection pool is bound to the event loop it was created on;
    the global singleton here has the same constraint but no per-test reset
    of its own, so a stale engine from a previous test's (now-closed) event
    loop would otherwise leak into this one. Dispose it before and after
    every test in this module so it's always (re)created fresh, bound to the
    current test's loop."""
    await db_session_module.dispose_engine()
    yield
    await db_session_module.dispose_engine()


class FakeJiraAdapter:
    def __init__(self, changed_issues: list[dict[str, Any]]) -> None:
        self.changed_issues = changed_issues
        self.queries: list[str] = []

    async def search_jql(self, jql: str, fields: list[str] | None = None, **kwargs: Any) -> dict:
        self.queries.append(jql)
        return {"issues": self.changed_issues, "isLast": True}

    async def aclose(self) -> None:
        pass


async def _make_run(session: AsyncSession, *, capability: str, status: RunStatus) -> AgentRun:
    run = AgentRun(capability=capability, trigger_source="test", status=status, checkpoint_json={})
    session.add(run)
    await session.flush()
    return run


async def test_poll_once_detects_externally_changed_issue(db_session: AsyncSession, monkeypatch) -> None:
    externally_changed = [{"key": "C3-42", "fields": {"summary": "Someone edited this in Jira"}}]
    fake_jira = FakeJiraAdapter(externally_changed)
    monkeypatch.setattr(poller, "_jira_factory", lambda: fake_jira)

    async def fake_check(session, *, project_key="C3", trigger_source="poller"):
        return RunContext(run_id=None, capability="x", trigger_source=trigger_source, data={"alerts": []})

    monkeypatch.setattr(blocker_dependency, "check", fake_check)
    monkeypatch.setattr(budget_watcher, "check", fake_check)

    from luna.config import Settings

    result = await poller.poll_once(project_key="C3", settings=Settings(jira_poll_interval_seconds=120))

    assert result["changed_issue_count"] == 1
    assert fake_jira.queries
    assert "updated >= -2m" in fake_jira.queries[0]
    assert "project = C3" in fake_jira.queries[0]


async def test_resume_pending_runs_skips_unconfirmed_status_intake(
    db_session: AsyncSession, monkeypatch
) -> None:
    resumed: list = []

    async def fake_resume_with_session(session, run_id):
        resumed.append(run_id)

        class _Ctx:
            status = RunStatus.completed

        return _Ctx()

    monkeypatch.setattr(poller, "resume_with_session", fake_resume_with_session)

    run = await _make_run(db_session, capability="status_intake", status=RunStatus.apply)
    db_session.add(
        Proposal(
            run_id=run.id,
            kind="status_transition",
            target_jira_key="C3-1",
            diff_json={"transition_id": "31"},
            status=ProposalStatus.pending,
            created_by_agent="status_intake",
            idempotency_key="poller-test-pending",
        )
    )
    await db_session.commit()

    await poller.resume_pending_runs()

    assert run.id not in resumed


async def test_resume_pending_runs_resumes_confirmed_status_intake(
    db_session: AsyncSession, monkeypatch
) -> None:
    resumed: list = []

    async def fake_resume_with_session(session, run_id):
        resumed.append(run_id)

        class _Ctx:
            status = RunStatus.completed

        return _Ctx()

    monkeypatch.setattr(poller, "resume_with_session", fake_resume_with_session)

    run = await _make_run(db_session, capability="status_intake", status=RunStatus.apply)
    db_session.add(
        Proposal(
            run_id=run.id,
            kind="status_transition",
            target_jira_key="C3-1",
            diff_json={"transition_id": "31"},
            status=ProposalStatus.confirmed,
            created_by_agent="status_intake",
            idempotency_key="poller-test-confirmed",
        )
    )
    await db_session.commit()

    await poller.resume_pending_runs()

    assert run.id in resumed


async def test_resume_pending_runs_resumes_other_capabilities_unconditionally(
    db_session: AsyncSession, monkeypatch
) -> None:
    resumed: list = []

    async def fake_resume_with_session(session, run_id):
        resumed.append(run_id)

        class _Ctx:
            status = RunStatus.completed

        return _Ctx()

    monkeypatch.setattr(poller, "resume_with_session", fake_resume_with_session)

    run = await _make_run(db_session, capability="blocker_dependency", status=RunStatus.decide)
    await db_session.commit()

    await poller.resume_pending_runs()

    assert run.id in resumed
