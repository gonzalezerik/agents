"""Capability #5 -- budget/margin watching (read-only/alerts).

Rolls up the `Mass (kg)`, `Power (W)`, `Cost (USD)`, `Data rate (kbps)`
custom fields by component + project total from Jira, compares each rollup
to the matching `budget` table row (component+metric), writes
`margin_snapshot` rows for history, and scores *overrun severity* (Score)
for anything with a configured budget. Read-only against Jira; the
`margin_snapshot` writes keep margin history in the sidecar DB -- not a
Jira write, so it is not gated by `guardrails.require_confirmation()`
(that gate is specifically for Jira writes, per guardrails.py's own
docstring).

## Custom field IDs are site-specific and currently placeholders

Jira custom fields get an opaque `customfield_NNNNN` id assigned by *that*
site at creation time -- there is no way to know the real ids before a real
Jira site exists (`seed/seed_jira.py` is what creates these fields, once a
site exists). `DEFAULT_CUSTOM_FIELD_MAP` below is a **placeholder** aimed at
making the shape/plumbing correct and testable now; whoever wires this
capability up against the real site must override it (pass
`custom_field_map` in `initial_data`, or update the default here) with the
ids `seed_jira.py` actually created.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna import control_loop
from luna.adapters.jira import JiraAdapter
from luna.audit import write_event
from luna.capabilities._session import current_session, run_with_session
from luna.control_loop import RunContext
from luna.db.models import Budget, MarginSnapshot, RunStatus
from luna.decision.engine import DecisionProvider, decide_many, get_decision_provider
from luna.decision.schemas import ScoreQuestion

CAPABILITY = "budget_watcher"

SEVERITY_LEVELS = ["under_budget", "near_limit", "at_limit", "over_budget", "critical_overrun"]

# Jira custom field display name -> our metric key (matches budget.metric /
# margin_snapshot.metric). See module docstring re: placeholder field ids.
METRIC_FIELD_NAMES: dict[str, str] = {
    "mass_kg": "Mass (kg)",
    "power_w": "Power (W)",
    "cost_usd": "Cost (USD)",
    "data_rate_kbps": "Data rate (kbps)",
}
DEFAULT_CUSTOM_FIELD_MAP: dict[str, str] = {
    "mass_kg": "customfield_10040",
    "power_w": "customfield_10041",
    "cost_usd": "customfield_10042",
    "data_rate_kbps": "customfield_10043",
}
TOTAL_COMPONENT = "__total__"

def _default_provider_factory() -> DecisionProvider:
    return get_decision_provider()


def _default_jira_factory() -> JiraAdapter:
    return JiraAdapter()


_provider_factory: Callable[[], DecisionProvider] = _default_provider_factory
_jira_factory: Callable[[], JiraAdapter] = _default_jira_factory


async def _retrieve(ctx: RunContext) -> RunContext:
    if "rollup" in ctx.data:
        return ctx  # test/caller-supplied rollup bypasses the Jira call

    project = ctx.data.get("project_key", "C3")
    field_map = ctx.data.get("custom_field_map") or DEFAULT_CUSTOM_FIELD_MAP
    jira = _jira_factory()
    try:
        resp = await jira.search_jql(
            f"project = {project}",
            fields=["components", *field_map.values()],
            max_results=200,
        )
    finally:
        await jira.aclose()

    rollup: dict[str, float] = {}
    for issue in resp.get("issues", []):
        fields = issue.get("fields", {})
        components = [c.get("name") for c in fields.get("components", [])] or ["Unassigned"]
        for metric_key, field_id in field_map.items():
            value = fields.get(field_id)
            if value is None:
                continue
            value = float(value)
            for comp in components:
                key = f"{comp}::{metric_key}"
                rollup[key] = rollup.get(key, 0.0) + value
            total_key = f"{TOTAL_COMPONENT}::{metric_key}"
            rollup[total_key] = rollup.get(total_key, 0.0) + value

    ctx.data["rollup"] = rollup
    return ctx


async def _decide(ctx: RunContext) -> RunContext:
    session = current_session()
    provider = _provider_factory()

    budgets_result = await session.execute(select(Budget))
    budgets = {(b.component, b.metric): b.limit_value for b in budgets_result.scalars().all()}

    snapshots: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []

    for key, value in ctx.data.get("rollup", {}).items():
        component, metric = key.split("::", 1)
        snapshots.append({"component": component, "metric": metric, "rolled_up_value": value})

        limit = budgets.get((component, metric))
        if limit is None:
            continue
        pct_of_budget = (value / limit) if limit else float("inf")
        state = {
            "component": component,
            "metric": metric,
            "rolled_up_value": value,
            "limit_value": limit,
            "pct_of_budget": pct_of_budget,
        }
        answers = await decide_many(
            session,
            ctx.run_id,
            provider,
            state,
            {
                "severity": ScoreQuestion(
                    instructions=(
                        "Given a component's rolled-up value against its budget limit "
                        "(see state), how severe is any overrun?"
                    ),
                    criteria=SEVERITY_LEVELS,
                )
            },
        )
        severity = answers["severity"]
        alerts.append(
            {
                "component": component,
                "metric": metric,
                "rolled_up_value": value,
                "limit_value": limit,
                "pct_of_budget": pct_of_budget,
                "severity_score": severity.score,
                "severity_legend": severity.legend,
                "breach": value > limit,
            }
        )

    ctx.data["snapshots"] = snapshots
    ctx.data["alerts"] = alerts
    return ctx


async def _plan(ctx: RunContext) -> RunContext:
    session = current_session()
    for snap in ctx.data.get("snapshots", []):
        session.add(
            MarginSnapshot(
                component=snap["component"],
                metric=snap["metric"],
                rolled_up_value=snap["rolled_up_value"],
            )
        )
    await session.flush()
    return ctx


async def _respond(ctx: RunContext) -> RunContext:
    session = current_session()
    breaches = [a for a in ctx.data.get("alerts", []) if a.get("breach")]
    await write_event(
        session,
        actor=CAPABILITY,
        action="respond.snapshots_written",
        run_id=ctx.run_id,
        result_ref=f"{len(ctx.data.get('snapshots', []))} snapshot(s), {len(breaches)} breach(es)",
    )
    return ctx


control_loop.register_node(CAPABILITY, RunStatus.retrieve, _retrieve)
control_loop.register_node(CAPABILITY, RunStatus.decide, _decide)
control_loop.register_node(CAPABILITY, RunStatus.plan, _plan)
control_loop.register_node(CAPABILITY, RunStatus.respond, _respond)


async def check(
    session: AsyncSession, *, project_key: str = "C3", trigger_source: str = "poller"
) -> RunContext:
    """Run the full budget rollup + severity check once, writing
    `margin_snapshot` rows, and return the `RunContext`
    (`.data["alerts"]`/`.data["snapshots"]`)."""
    return await run_with_session(
        session,
        capability=CAPABILITY,
        trigger_source=trigger_source,
        initial_data={"project_key": project_key},
    )
