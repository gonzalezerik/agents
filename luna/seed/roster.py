"""C3 rover team roster + idempotent Postgres seeding.

## Placeholder names

The names below are placeholders -- replace them with the real team before
seeding. A member on two subteams is one roster row with two `subteams`
entries (e.g. Robin: [Chassis, Processing]); two different people who share a
first name are told apart by last initial ("Sam" vs "Sam Y.").

## Licensing

`licensed_bool` defaults to `False` for everyone: no real Jira site/roster
of actual licensed seats exists yet,
so nothing here is "obviously" licensed. Set these explicitly once real
Jira account ids are assigned.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.db.models import Roster


@dataclass(frozen=True)
class RosterEntry:
    name: str
    subteams: list[str]
    licensed_bool: bool = False


ROSTER: list[RosterEntry] = [
    RosterEntry("Alex", ["Chassis"]),
    RosterEntry("Blake", ["Chassis"]),
    RosterEntry("Casey", ["Chassis"]),
    RosterEntry("Drew", ["Chassis"]),
    RosterEntry("Emery", ["Chassis"]),
    RosterEntry("Robin", ["Chassis", "Processing"]),
    RosterEntry("Parker", ["Power"]),
    RosterEntry("Quinn", ["Power"]),
    RosterEntry("Reese", ["Power"]),
    RosterEntry("Sam Y.", ["Power"]),
    RosterEntry("Taylor", ["Power", "Processing"]),
    RosterEntry("Harper", ["Systems-Architecture"]),
    RosterEntry("Jordan", ["Systems-Architecture"]),
    RosterEntry("Eden", ["Systems-Architecture"]),
    RosterEntry("Kai", ["Systems-Architecture"]),
    RosterEntry("Morgan", ["Systems-Architecture"]),
    RosterEntry("Jules", ["Excavation"]),
    RosterEntry("Frankie", ["Excavation"]),
    RosterEntry("Sam", ["Excavation"]),
    RosterEntry("River", ["Excavation", "Processing"]),
]


async def seed_roster(session: AsyncSession) -> list[Roster]:
    """Idempotent (check-before-create by exact `name` match) upsert of
    `ROSTER` into the `roster` table. Runs standalone against Postgres with
    no Jira credentials at all -- this is the half `python -m seed.seed_jira
    --roster-only` exercises.

    Re-running is safe: an existing row's `subteams` is updated to match
    `ROSTER` (in case the roster changes) but `discord_id`/`slack_id`/
    `jira_account_id` are left untouched, since those get populated by other
    integration paths later (Discord/Slack onboarding, Jira account linking)
    and this script has no business overwriting them with nulls on a re-run.
    """
    rows: list[Roster] = []
    for entry in ROSTER:
        result = await session.execute(select(Roster).where(Roster.name == entry.name))
        existing = result.scalar_one_or_none()
        if existing is None:
            row = Roster(
                name=entry.name,
                subteams=list(entry.subteams),
                licensed_bool=entry.licensed_bool,
            )
            session.add(row)
            rows.append(row)
        else:
            if existing.subteams != entry.subteams:
                existing.subteams = list(entry.subteams)
            rows.append(existing)
    await session.flush()
    return rows
