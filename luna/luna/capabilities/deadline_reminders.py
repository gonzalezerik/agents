"""Capability #8 -- deadline reminders (read-only/posts).

Maps Jira versions (release dates = C3 competition/class milestones) to
scheduled reminders with configurable lead times.
`luna/workers/scheduler.py` drives `check()` on an interval; each run lists
Jira versions, computes days-until-release, and for any version whose
days-until exactly crosses a configured lead time produces a reminder
payload.

No Decision Engine question is asked here -- "is this version N days out"
is a deterministic date computation, not a semantic judgment (unlike
#1/#4/#5). `decide` is therefore a plain data-transform node, not a
`decide_many()` call -- kept as a separate node anyway (rather than folded
into `retrieve`) so it stays easy to slot a real question in later if one
is ever needed (e.g. "how urgently should this be reworded for a
near-term deadline").

## Reminder payload shape (for the Discord/Slack adapters)

`ctx.data["reminders"]` is a list of:
```
{
    "version_id": str, "version_name": str, "release_date": str (ISO date),
    "days_until": int, "lead_time_days": int, "detail": str,
}
```
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from luna import control_loop
from luna.adapters.jira import JiraAdapter
from luna.audit import write_event
from luna.capabilities._session import current_session, run_with_session
from luna.control_loop import RunContext
from luna.db.models import RunStatus

CAPABILITY = "deadline_reminders"

DEFAULT_LEAD_TIMES_DAYS = [30, 14, 7, 3, 1]

def _default_jira_factory() -> JiraAdapter:
    return JiraAdapter()


_jira_factory: Callable[[], JiraAdapter] = _default_jira_factory


def _today(ctx_data: dict) -> date:
    override = ctx_data.get("today")
    return date.fromisoformat(override) if override else date.today()


async def _retrieve(ctx: RunContext) -> RunContext:
    if "versions" in ctx.data:
        return ctx  # test/caller-supplied versions bypass the Jira call

    jira = _jira_factory()
    project = ctx.data.get("project_key", "C3")
    try:
        versions = await jira.list_versions(project)
    finally:
        await jira.aclose()
    ctx.data["versions"] = versions
    return ctx


async def _decide(ctx: RunContext) -> RunContext:
    lead_times = ctx.data.get("lead_time_days") or DEFAULT_LEAD_TIMES_DAYS
    today = _today(ctx.data)
    reminders = []

    for version in ctx.data.get("versions", []):
        if version.get("released"):
            continue
        release_date_raw = version.get("releaseDate")
        if not release_date_raw:
            continue
        release_date = date.fromisoformat(release_date_raw)
        days_until = (release_date - today).days
        if days_until < 0:
            continue
        for lead in lead_times:
            if days_until == lead:
                reminders.append(
                    {
                        "version_id": version.get("id"),
                        "version_name": version.get("name"),
                        "release_date": release_date_raw,
                        "days_until": days_until,
                        "lead_time_days": lead,
                        "detail": (
                            f"{version.get('name')} is due in {days_until} day(s) "
                            f"({release_date_raw})"
                        ),
                    }
                )
    ctx.data["reminders"] = reminders
    return ctx


async def _respond(ctx: RunContext) -> RunContext:
    session = current_session()
    await write_event(
        session,
        actor=CAPABILITY,
        action="respond.reminders_ready",
        run_id=ctx.run_id,
        result_ref=f"{len(ctx.data.get('reminders', []))} reminder(s)",
    )
    return ctx


control_loop.register_node(CAPABILITY, RunStatus.retrieve, _retrieve)
control_loop.register_node(CAPABILITY, RunStatus.decide, _decide)
control_loop.register_node(CAPABILITY, RunStatus.respond, _respond)


async def check(
    session: AsyncSession,
    *,
    project_key: str = "C3",
    lead_time_days: list[int] | None = None,
    trigger_source: str = "scheduler",
) -> RunContext:
    """Run the deadline-reminder check once and return the `RunContext`
    (`.data["reminders"]`)."""
    initial_data: dict = {"project_key": project_key}
    if lead_time_days is not None:
        initial_data["lead_time_days"] = lead_time_days
    return await run_with_session(
        session, capability=CAPABILITY, trigger_source=trigger_source, initial_data=initial_data
    )
