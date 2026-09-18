"""JQL poller loop (`luna-worker`) -- spec §3.8, CONTRACT.md.

On each tick: `search_jql("updated >= -{N}m")` to detect issues that changed
externally since the last tick (spec §4.4 verification criterion #3: "poller
detects an externally-made change within one interval"), then runs the
read-only alert capabilities (#4 `blocker_dependency`, #5 `budget_watcher`),
which each re-derive their own full current view from Jira rather than
reacting to the delta -- simpler and correct at this project's scale (one
Jira project, dozens of issues), and it means the interval-JQL result here is
used purely for change *detection*/logging, not as the sole input to the
alert capabilities.

## Resume-on-startup, with one deliberate carve-out

CONTRACT.md: "workers/poller.py and the API's proposal-confirm handler both
call `control_loop.resume(run_id)` on startup for any `agent_run` left in a
non-terminal state." Followed literally for every capability *except*
`status_intake` runs sitting at `RunStatus.apply` -- those are deliberately
paused, waiting for a human to hit Confirm (see
`luna/capabilities/status_intake.py`'s module docstring for why
`control_loop.run()` can't express "pause here" any other way). Blindly
resuming one of those would force an *unconfirmed* proposal's `apply` node to
run. This poller only resumes such a run if its `Proposal` is already
`confirmed` (meaning a confirm genuinely happened and the apply drive itself
got interrupted -- e.g. the worker process crashed between the confirm route
committing `Proposal.status=confirmed` and `resume()` finishing); a
still-`pending` (or `cancelled`) proposal's run is left alone for
`api/routes/proposals.py`'s confirm handler to resume later (or, for
`cancelled`, never -- see that route's own handling).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import select

from luna.adapters.jira import JiraAdapter
from luna.capabilities import blocker_dependency, budget_watcher
from luna.capabilities._session import resume_with_session
from luna.config import Settings, get_settings
from luna.db.models import NON_TERMINAL_RUN_STATUSES, AgentRun, Proposal, ProposalStatus, RunStatus
from luna.db.session import session_scope

logger = logging.getLogger("luna.worker.poller")

def _default_jira_factory() -> JiraAdapter:
    return JiraAdapter()


_jira_factory: Callable[[], JiraAdapter] = _default_jira_factory


async def resume_pending_runs() -> None:
    """Call once at worker startup."""
    async with session_scope() as session:
        result = await session.execute(
            select(AgentRun).where(AgentRun.status.in_(NON_TERMINAL_RUN_STATUSES))
        )
        runs = result.scalars().all()
        for run in runs:
            if run.capability == "status_intake" and run.status == RunStatus.apply:
                proposal_result = await session.execute(
                    select(Proposal).where(Proposal.run_id == run.id)
                )
                proposal = proposal_result.scalar_one_or_none()
                if proposal is None or proposal.status != ProposalStatus.confirmed:
                    logger.info(
                        "poller: leaving status_intake run %s at apply -- proposal not confirmed yet",
                        run.id,
                    )
                    continue
            logger.info("poller: resuming agent_run %s (%s, %s)", run.id, run.capability, run.status)
            try:
                await resume_with_session(session, run.id)
            except Exception:
                logger.exception("poller: resume failed for agent_run %s", run.id)


async def poll_once(*, project_key: str, settings: Settings | None = None) -> dict:
    """One poll tick. Returns a small summary dict, mostly useful for tests
    and logging."""
    settings = settings or get_settings()
    interval_minutes = max(1, settings.jira_poll_interval_seconds // 60)

    jira = _jira_factory()
    try:
        changed = await jira.search_jql(
            f"project = {project_key} AND updated >= -{interval_minutes}m",
            fields=["updated", "summary"],
        )
    finally:
        await jira.aclose()

    async with session_scope() as session:
        blocker_ctx = await blocker_dependency.check(session, project_key=project_key)
        budget_ctx = await budget_watcher.check(session, project_key=project_key)

    return {
        "changed_issue_count": len(changed.get("issues", [])),
        "blocker_alerts": blocker_ctx.data.get("alerts", []),
        "budget_alerts": budget_ctx.data.get("alerts", []),
    }


async def run_forever(*, project_key: str = "C3") -> None:
    settings = get_settings()
    await resume_pending_runs()
    while True:
        try:
            await poll_once(project_key=project_key, settings=settings)
        except Exception:
            logger.exception("poller: tick failed")
        await asyncio.sleep(settings.jira_poll_interval_seconds)
