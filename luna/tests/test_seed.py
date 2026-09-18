"""Tests for `seed/roster.py` (fully standalone against Postgres, no Jira
needed -- this is what `python -m seed.seed_jira --roster-only` exercises)
and a couple of `seed/seed_jira.py`'s Jira-side check-before-create helpers
against a `respx`-mocked Jira, since there is no real site to test end to
end (see `luna/adapters/jira.py`'s module docstring)."""

from __future__ import annotations

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.adapters.jira import JiraAdapter
from luna.config import Settings
from luna.db.models import Roster
from seed import seed_jira
from seed.roster import ROSTER, seed_roster

BASE = "https://testsite.atlassian.net/rest/api/3"


def _settings() -> Settings:
    return Settings(jira_site="testsite", jira_email="bot@example.com", jira_api_token="tok")


async def test_seed_roster_creates_all_entries(db_session: AsyncSession) -> None:
    rows = await seed_roster(db_session)
    assert len(rows) == len(ROSTER)

    result = await db_session.execute(select(Roster))
    names = {r.name for r in result.scalars().all()}
    assert names == {e.name for e in ROSTER}


async def test_seed_roster_merges_two_subteam_members_correctly(db_session: AsyncSession) -> None:
    await seed_roster(db_session)
    result = await db_session.execute(select(Roster).where(Roster.name == "Robin"))
    robert = result.scalar_one()
    assert set(robert.subteams) == {"Chassis", "Processing"}

    result = await db_session.execute(select(Roster).where(Roster.name == "Taylor"))
    omar = result.scalar_one()
    assert set(omar.subteams) == {"Power", "Processing"}

    result = await db_session.execute(select(Roster).where(Roster.name == "River"))
    raul = result.scalar_one()
    assert set(raul.subteams) == {"Excavation", "Processing"}

    # "Sam" (Excavation) and "Sam Y." (Power) stay distinct people.
    result = await db_session.execute(select(Roster).where(Roster.name.in_(["Sam", "Sam Y."])))
    anthonys = {r.name: set(r.subteams) for r in result.scalars().all()}
    assert anthonys == {"Sam": {"Excavation"}, "Sam Y.": {"Power"}}


async def test_seed_roster_is_idempotent(db_session: AsyncSession) -> None:
    await seed_roster(db_session)
    result = await db_session.execute(select(Roster))
    count_first = len(result.scalars().all())

    await seed_roster(db_session)
    result = await db_session.execute(select(Roster))
    rows_second = result.scalars().all()

    assert len(rows_second) == count_first  # no duplicates created
    assert len(rows_second) == len(ROSTER)


async def test_seed_roster_preserves_existing_jira_account_id(db_session: AsyncSession) -> None:
    await seed_roster(db_session)
    result = await db_session.execute(select(Roster).where(Roster.name == "Alex"))
    juan = result.scalar_one()
    juan.jira_account_id = "5f9-already-linked"
    await db_session.flush()

    await seed_roster(db_session)  # re-run must not clobber it
    result = await db_session.execute(select(Roster).where(Roster.name == "Alex"))
    juan_again = result.scalar_one()
    assert juan_again.jira_account_id == "5f9-already-linked"


@respx.mock
async def test_ensure_components_creates_only_missing() -> None:
    respx.get(f"{BASE}/project/C3/components").mock(
        return_value=httpx.Response(200, json=[{"id": "1", "name": "Chassis"}])
    )
    create_route = respx.post(f"{BASE}/component").mock(
        return_value=httpx.Response(201, json={"id": "2", "name": "Power"})
    )
    jira = JiraAdapter(_settings())
    try:
        result = await seed_jira._ensure_components(jira, "C3")
    finally:
        await jira.aclose()

    assert "Chassis" not in result["created"]
    assert set(result["created"]) == set(seed_jira.COMPONENTS) - {"Chassis"}
    assert create_route.call_count == len(seed_jira.COMPONENTS) - 1


@respx.mock
async def test_ensure_components_all_already_present_creates_nothing() -> None:
    respx.get(f"{BASE}/project/C3/components").mock(
        return_value=httpx.Response(
            200, json=[{"id": str(i), "name": name} for i, name in enumerate(seed_jira.COMPONENTS)]
        )
    )
    create_route = respx.post(f"{BASE}/component").mock(return_value=httpx.Response(201, json={}))
    jira = JiraAdapter(_settings())
    try:
        result = await seed_jira._ensure_components(jira, "C3")
    finally:
        await jira.aclose()

    assert result["created"] == []
    assert create_route.call_count == 0


@respx.mock
async def test_ensure_versions_creates_only_missing_with_dates() -> None:
    respx.get(f"{BASE}/project/C3/versions").mock(
        return_value=httpx.Response(200, json=[{"id": "1", "name": "PDR"}])
    )
    create_route = respx.post(f"{BASE}/version").mock(return_value=httpx.Response(201, json={"id": "9"}))
    jira = JiraAdapter(_settings())
    try:
        result = await seed_jira._ensure_versions(jira, "C3")
    finally:
        await jira.aclose()

    assert "PDR" not in result["created"]
    created_names = {name for name, _ in seed_jira.VERSIONS} - {"PDR"}
    assert set(result["created"]) == created_names
    assert create_route.call_count == len(created_names)

    sent_bodies = [call.request.content for call in create_route.calls]
    assert any(b"Midpoint-Showcase-2026-12" in body and b"2026-12-11" in body for body in sent_bodies)
