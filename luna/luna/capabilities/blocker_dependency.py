"""Capability #4 -- blocker/stale detection + cross-subteam dependency
conflict alerts (read-only/alerts), spec §3.3 #4.

Polls JQL for `status = Blocked`, staleness (`updated <= -5d` and not Done),
and issues carrying issue-links (a best-effort proxy for "crosses
components" -- see `_retrieve`'s docstring). For each candidate, the
Decision Engine scores *is this a real cross-subteam dependency risk?*
(Score) and *should we alert now?* (Noul). This capability never writes to
Jira; `check()` runs it start-to-finish through the real, unmodified
`control_loop.run()` (no gate/apply/confirm needed -- read-only).

## Alert payload shape (for the Discord/Slack adapter builder)

`ctx.data["alerts"]` (also the return value's `.data["alerts"]`) is a list
of:
```
{
    "jira_key": str,
    "summary": str | None,
    "reason": "blocked" | "stale" | "cross_component_link",
    "reasons": list[str],           # every reason that matched, not just the first
    "components": list[str],
    "risk_score": float,            # 0..len(RISK_LEVELS)-1, probability-weighted
    "risk_legend": dict[str, str],  # level index (str) -> label
    "should_alert_now": bool,       # Noul answer thresholded at 0.5
    "should_alert_noul": float,     # raw 0..1
    "detail": str,                  # human-readable one-liner
}
```
Route these to the relevant subteam channel(s) (derive from `components`)
plus the PM/Admin channel per spec -- this module has no notion of Discord/
Slack channel IDs, that's the adapter's job.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from luna import control_loop
from luna.adapters.jira import JiraAdapter
from luna.audit import write_event
from luna.capabilities._session import current_session, run_with_session
from luna.control_loop import RunContext
from luna.db.models import RunStatus
from luna.decision.engine import DecisionProvider, decide_many, get_decision_provider
from luna.decision.schemas import NoulQuestion, ScoreQuestion

CAPABILITY = "blocker_dependency"

RISK_LEVELS = ["none", "low", "medium", "high", "critical"]

BLOCKED_JQL = "project = {project} AND status = Blocked"
STALE_JQL = "project = {project} AND status != Done AND updated <= -5d"
SEARCH_FIELDS = ["summary", "status", "components", "updated", "issuelinks"]

def _default_provider_factory() -> DecisionProvider:
    return get_decision_provider()


def _default_jira_factory() -> JiraAdapter:
    return JiraAdapter()


_provider_factory: Callable[[], DecisionProvider] = _default_provider_factory
_jira_factory: Callable[[], JiraAdapter] = _default_jira_factory


async def _retrieve(ctx: RunContext) -> RunContext:
    """Merges the Blocked-status and stale-issue JQL result sets by issue
    key (an issue can match both), tagging each with which reason(s)
    matched. Cross-component links are a **best-effort heuristic**: an issue
    with any `issuelinks` entries is flagged `cross_component_link` without
    fetching the linked issue's own components (that would cost one extra
    Jira call per link) -- genuinely resolving "does this link cross a
    component boundary" needs that extra fetch, noted as a documented
    simplification, not a guess presented as exact."""
    if "candidates" in ctx.data:
        return ctx  # test/caller-supplied candidates bypass the Jira calls

    jira = _jira_factory()
    project = ctx.data.get("project_key", "C3")
    try:
        blocked = await jira.search_jql(BLOCKED_JQL.format(project=project), fields=SEARCH_FIELDS)
        stale = await jira.search_jql(STALE_JQL.format(project=project), fields=SEARCH_FIELDS)
    finally:
        await jira.aclose()

    merged: dict[str, dict[str, Any]] = {}
    for reason, resp in (("blocked", blocked), ("stale", stale)):
        for issue in resp.get("issues", []):
            key = issue["key"]
            entry = merged.setdefault(
                key, {"key": key, "fields": issue.get("fields", {}), "reasons": set()}
            )
            entry["reasons"].add(reason)

    candidates = []
    for entry in merged.values():
        fields = entry["fields"]
        reasons = entry["reasons"]
        if fields.get("issuelinks"):
            reasons.add("cross_component_link")
        candidates.append(
            {
                "key": entry["key"],
                "summary": fields.get("summary"),
                "components": [c.get("name") for c in fields.get("components", [])],
                "reasons": sorted(reasons),
            }
        )
    ctx.data["candidates"] = candidates
    return ctx


async def _decide(ctx: RunContext) -> RunContext:
    session = current_session()
    provider = _provider_factory()
    alerts: list[dict[str, Any]] = []

    for candidate in ctx.data.get("candidates", []):
        state = {
            "key": candidate["key"],
            "summary": candidate.get("summary"),
            "components": candidate.get("components", []),
            "reasons": candidate.get("reasons", []),
        }
        questions = {
            "risk": ScoreQuestion(
                instructions=(
                    "This Jira issue is blocked, stale, and/or cross-linked (see "
                    "state.reasons). How much of a real cross-subteam dependency risk "
                    "does it represent to the team?"
                ),
                criteria=RISK_LEVELS,
            ),
            "alert": NoulQuestion(
                instructions="Should the team be alerted about this issue right now, as opposed to waiting?"
            ),
        }
        answers = await decide_many(session, ctx.run_id, provider, state, questions)
        risk = answers["risk"]
        alert_noul = answers["alert"].noul
        reasons = candidate.get("reasons", [])
        alerts.append(
            {
                "jira_key": candidate["key"],
                "summary": candidate.get("summary"),
                "reason": reasons[0] if reasons else "unknown",
                "reasons": reasons,
                "components": candidate.get("components", []),
                "risk_score": risk.score,
                "risk_legend": risk.legend,
                "should_alert_now": alert_noul >= 0.5,
                "should_alert_noul": alert_noul,
                "detail": (
                    f"{candidate['key']} ({', '.join(reasons)}) -- risk "
                    f"{risk.score:.1f}/{len(RISK_LEVELS) - 1}"
                ),
            }
        )
    ctx.data["alerts"] = alerts
    return ctx


async def _respond(ctx: RunContext) -> RunContext:
    session = current_session()
    alerts = ctx.data.get("alerts", [])
    to_alert = [a for a in alerts if a.get("should_alert_now")]
    await write_event(
        session,
        actor=CAPABILITY,
        action="respond.alerts_ready",
        run_id=ctx.run_id,
        result_ref=f"{len(to_alert)}/{len(alerts)} alert(s) to send now",
    )
    return ctx


control_loop.register_node(CAPABILITY, RunStatus.retrieve, _retrieve)
control_loop.register_node(CAPABILITY, RunStatus.decide, _decide)
control_loop.register_node(CAPABILITY, RunStatus.respond, _respond)


async def check(
    session: AsyncSession, *, project_key: str = "C3", trigger_source: str = "poller"
) -> RunContext:
    """Run the full blocker/dependency check once and return the resulting
    `RunContext` (`.data["alerts"]` is what callers want)."""
    return await run_with_session(
        session,
        capability=CAPABILITY,
        trigger_source=trigger_source,
        initial_data={"project_key": project_key},
    )
