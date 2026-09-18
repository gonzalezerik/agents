"""C3 rover team roster (spec §3.2) + idempotent Postgres seeding.

## Name normalization note

Spec §3.2 lists the roster with a few names carrying a "-2nd" suffix (e.g.
"Robin-2nd" under Chassis, "Taylor-2nd" under Power, "River-2nd" under
Excavation) alongside an unsuffixed instance of the same first name listed
under Processing (Robin, River, Taylor). Read together with the spec's own
text -- "Members on two subteams get issues in either component" and
"several members are on two subteams" (§3.2, §4.5) -- the "-2nd" suffix
denotes "this name's *second* subteam", not a distinct person literally
named e.g. "Robin-2nd". This module merges those into one roster row each,
with two `subteams` entries:

- Robin: [Chassis, Processing]
- Taylor: [Power, Processing]
- River: [Excavation, Processing]

"Sam" (Excavation) and "Sam Y." (Power) are kept as two distinct
people -- the spec text itself disambiguates them with the last initial, so
merging them would be the wrong call.

## Licensing

`licensed_bool` defaults to `False` for everyone: no real Jira site/roster
of actual licensed seats exists yet (spec §3.2's licensing decision --
academic discount vs. ~10-seat + LUNA-proxy fallback -- hasn't been made),
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
    `ROSTER` (in case the spec roster changes) but `discord_id`/`slack_id`/
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
