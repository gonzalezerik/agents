"""`seed/seed_jira.py` -- idempotent Jira + roster seed script.

Two independent halves:

1. **Jira seeding** -- components, custom fields, issue types, the
   `Blocked` workflow status, versions mapped to C3 milestones, one Epic per
   subteam/component, and a starter Requirement/Risk/Test per subteam.
   Requires `JIRA_SITE`/`JIRA_EMAIL`/`JIRA_API_TOKEN` and a real Jira Cloud
   site. **No real site exists yet** (a known, permanent gap until a human
   creates one -- Atlassian requires interactive signup, there is no
   provisioning API). This half fails fast and clearly
   (`JiraNotConfiguredError`, or a normal `httpx` error against whatever URL
   is configured) rather than hanging or silently skipping.
2. **Roster seeding** (`seed.roster`) -- writes the C3 roster into the
   `roster` Postgres table. Fully standalone, no Jira credentials needed:
   `python -m seed.seed_jira --roster-only`.

## Idempotency

Every Jira resource type is **check-before-create**: list what already
exists, create only what's missing (matched by name/summary), so re-running
the whole script against an already-seeded site is a no-op on everything
already present. This is a different idempotency mechanism than
`guardrails.compute_idempotency_key`/`Proposal.idempotency_key` (that
machinery is for the proposal->confirm->apply lifecycle; seed isn't part of
it -- see `JiraAdapter`'s write methods, which accept `session=None` for
exactly this caller).

## Usage

```
python -m seed.seed_jira                 # full seed: Jira + roster
python -m seed.seed_jira --roster-only    # roster only, no Jira required
python -m seed.seed_jira --jira-only      # Jira only, skip roster
python -m seed.seed_jira --project-key C3 # override the default project key
```
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from luna.adapters.jira import JiraAdapter
from luna.db.session import session_scope
from seed.roster import seed_roster

logger = logging.getLogger("seed.seed_jira")

DEFAULT_PROJECT_KEY = "C3"

COMPONENTS = [
    "Chassis",
    "Power",
    "Systems-Architecture",
    "Excavation",
    "Processing",
    "Integration",
    "Admin/PM",
]

# (display name, Jira custom-field-type key). Number fields use the "float"
# type (Jira has no separate int/float custom field type distinction beyond
# format). Selects are created plain (no options set here -- option values
# would need a follow-up `PUT /field/{id}/context/{contextId}/option` call
# per context, out of scope for a first pass; documented, not silently
# skipped).
CUSTOM_FIELDS: list[tuple[str, str]] = [
    ("Subteam", "com.atlassian.jira.plugin.system.customfieldtypes:select"),
    ("Requirement ID", "com.atlassian.jira.plugin.system.customfieldtypes:textfield"),
    ("Verification Method", "com.atlassian.jira.plugin.system.customfieldtypes:select"),
    ("Mass (kg)", "com.atlassian.jira.plugin.system.customfieldtypes:float"),
    ("Power (W)", "com.atlassian.jira.plugin.system.customfieldtypes:float"),
    ("Cost (USD)", "com.atlassian.jira.plugin.system.customfieldtypes:float"),
    ("Data rate (kbps)", "com.atlassian.jira.plugin.system.customfieldtypes:float"),
    ("Risk Likelihood", "com.atlassian.jira.plugin.system.customfieldtypes:float"),
    ("Risk Impact", "com.atlassian.jira.plugin.system.customfieldtypes:float"),
    ("Risk Score", "com.atlassian.jira.plugin.system.customfieldtypes:float"),
    ("Competition Milestone", "com.atlassian.jira.plugin.system.customfieldtypes:select"),
    ("Confidence-source", "com.atlassian.jira.plugin.system.customfieldtypes:textfield"),
]

# Requirement/Risk/Test/Decision(ADR)/Procurement-BOM-Item are custom issue
# types LUNA uses; Epic/Story/Task/Sub-task/Bug already exist on
# every Jira project by default and are not (re)created here.
ISSUE_TYPES = ["Requirement", "Risk", "Test", "Decision (ADR)", "Procurement/BOM Item"]

BLOCKED_STATUS_NAME = "Blocked"

# (version name, release date ISO 8601 or None): C3 competition and class milestones.
VERSIONS: list[tuple[str, str | None]] = [
    ("Statement-of-Intent", None),
    ("PDR", None),
    ("Midpoint-Showcase-2026-12", "2026-12-11"),
    ("Prototype-Test-Marshall-2027-04", "2027-04-09"),
    ("Final-Judging-2027-04", "2027-04-16"),
    ("COMP490-Final", None),
    ("COMP491-MVP", None),
]


async def _ensure_components(jira: JiraAdapter, project_key: str) -> dict[str, Any]:
    existing = {c["name"] for c in await jira.list_components(project_key)}
    created = []
    for name in COMPONENTS:
        if name in existing:
            continue
        await jira.create_component(project_key, name=name)
        created.append(name)
    return {"existing": sorted(existing), "created": created}


async def _ensure_custom_fields(jira: JiraAdapter) -> dict[str, Any]:
    existing = {f["name"] for f in await jira.list_fields() if f.get("custom")}
    created = []
    for name, field_type in CUSTOM_FIELDS:
        if name in existing:
            continue
        await jira.create_field(name=name, field_type=field_type)
        created.append(name)
    return {"existing": sorted(existing), "created": created}


async def _ensure_issue_types(jira: JiraAdapter) -> dict[str, Any]:
    existing = {t["name"] for t in await jira.list_issue_types()}
    created = []
    for name in ISSUE_TYPES:
        if name in existing:
            continue
        await jira.create_issue_type(name=name)
        created.append(name)
    return {"existing": sorted(existing), "created": created}


async def _ensure_blocked_status(jira: JiraAdapter) -> dict[str, Any]:
    existing = {s["name"] for s in await jira.list_statuses()}
    if BLOCKED_STATUS_NAME in existing:
        return {"existing": True, "created": False}
    await jira.create_global_status(name=BLOCKED_STATUS_NAME, status_category="TODO")
    logger.warning(
        "seed_jira: created the '%s' status resource, but it is NOT yet wired into any "
        "project's workflow transitions -- that requires a separate, plan-tier-dependent "
        "workflow edit (see JiraAdapter.create_global_status's docstring). Add it to the "
        "workflow manually (or via the Workflow API) before relying on it.",
        BLOCKED_STATUS_NAME,
    )
    return {"existing": False, "created": True}


async def _ensure_versions(jira: JiraAdapter, project_key: str) -> dict[str, Any]:
    existing = {v["name"] for v in await jira.list_versions(project_key)}
    created = []
    for name, release_date in VERSIONS:
        if name in existing:
            continue
        await jira.create_version(project_key, name=name, release_date=release_date)
        created.append(name)
    return {"existing": sorted(existing), "created": created}


async def _find_existing_summaries(jira: JiraAdapter, project_key: str, issuetype: str) -> set[str]:
    resp = await jira.search_jql(
        f'project = {project_key} AND issuetype = "{issuetype}"', fields=["summary"], max_results=200
    )
    return {issue.get("fields", {}).get("summary") for issue in resp.get("issues", [])}


async def _ensure_issue(
    jira: JiraAdapter,
    project_key: str,
    *,
    issuetype: str,
    summary: str,
    component: str,
    existing_summaries: set[str],
) -> bool:
    """Returns True if created, False if it already existed."""
    if summary in existing_summaries:
        return False
    await jira.create_issue(
        fields={
            "project": {"key": project_key},
            "issuetype": {"name": issuetype},
            "summary": summary,
            "components": [{"name": component}],
        },
        idempotency_key=f"seed:{issuetype}:{project_key}:{summary}",
    )
    return True


async def _ensure_epics_and_starters(jira: JiraAdapter, project_key: str) -> dict[str, Any]:
    epic_summaries = await _find_existing_summaries(jira, project_key, "Epic")
    req_summaries = await _find_existing_summaries(jira, project_key, "Requirement")
    risk_summaries = await _find_existing_summaries(jira, project_key, "Risk")
    test_summaries = await _find_existing_summaries(jira, project_key, "Test")

    created: dict[str, list[str]] = {"Epic": [], "Requirement": [], "Risk": [], "Test": []}
    for subteam in COMPONENTS:
        epic_summary = f"{subteam} Epic"
        if await _ensure_issue(
            jira,
            project_key,
            issuetype="Epic",
            summary=epic_summary,
            component=subteam,
            existing_summaries=epic_summaries,
        ):
            created["Epic"].append(epic_summary)

        req_summary = f"{subteam} starter requirement"
        if await _ensure_issue(
            jira,
            project_key,
            issuetype="Requirement",
            summary=req_summary,
            component=subteam,
            existing_summaries=req_summaries,
        ):
            created["Requirement"].append(req_summary)

        risk_summary = f"{subteam} starter risk"
        if await _ensure_issue(
            jira,
            project_key,
            issuetype="Risk",
            summary=risk_summary,
            component=subteam,
            existing_summaries=risk_summaries,
        ):
            created["Risk"].append(risk_summary)

        test_summary = f"{subteam} starter test"
        if await _ensure_issue(
            jira,
            project_key,
            issuetype="Test",
            summary=test_summary,
            component=subteam,
            existing_summaries=test_summaries,
        ):
            created["Test"].append(test_summary)

    return created


async def seed_jira(project_key: str = DEFAULT_PROJECT_KEY) -> dict[str, Any]:
    """Runs the full Jira-side seed, in dependency order (components/fields/
    issue types/status/versions before the issues that reference them).
    Raises (does not swallow) on any failure -- fail loudly and
    specifically."""
    jira = JiraAdapter()
    try:
        summary: dict[str, Any] = {}
        summary["components"] = await _ensure_components(jira, project_key)
        summary["custom_fields"] = await _ensure_custom_fields(jira)
        summary["issue_types"] = await _ensure_issue_types(jira)
        summary["blocked_status"] = await _ensure_blocked_status(jira)
        summary["versions"] = await _ensure_versions(jira, project_key)
        summary["epics_and_starters"] = await _ensure_epics_and_starters(jira, project_key)
        return summary
    finally:
        await jira.aclose()


async def main_async(*, project_key: str, roster_only: bool, jira_only: bool) -> None:
    logging.basicConfig(level=logging.INFO)

    if not jira_only:
        async with session_scope() as session:
            roster_rows = await seed_roster(session)
        logger.info("seed_jira: roster seeded (%d entries)", len(roster_rows))

    if not roster_only:
        summary = await seed_jira(project_key=project_key)
        logger.info("seed_jira: Jira seed complete: %s", summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-key", default=DEFAULT_PROJECT_KEY)
    parser.add_argument(
        "--roster-only", action="store_true", help="seed only the Postgres roster table, no Jira calls"
    )
    parser.add_argument(
        "--jira-only", action="store_true", help="seed only Jira, skip the Postgres roster table"
    )
    args = parser.parse_args()
    if args.roster_only and args.jira_only:
        parser.error("--roster-only and --jira-only are mutually exclusive")
    asyncio.run(
        main_async(project_key=args.project_key, roster_only=args.roster_only, jira_only=args.jira_only)
    )


if __name__ == "__main__":
    main()
