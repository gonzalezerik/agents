"""Capability #2 -- standup / weekly summaries (spec §3.3 #2, CONTRACT.md).

Read-only against Jira. Drafts each roster member's update from their recent
Jira activity (Troopr-style two-stage provenance: LUNA drafts, the person
edits before it's actually posted), extracts blockers via the Decision
Engine, and flags candidate new action items that don't look like they're
already tracked as their own Jira ticket. `run_standup()` never posts
anything itself -- see "Output shape" below -- and per spec "#2 may create
action-item proposals routed through #3's confirm flow," flagged action-item
candidates are handed to `meeting_action_items.propose_action_items()` (this
build's own capability #3) so they go through the identical
proposal->confirm->apply path, rather than this module inventing a second
write path.

## Jira adapter interface this module depends on

`luna/adapters/jira.py` is another builder's file and does not exist yet in
this worktree (CONTRACT.md scope). This module is written against the
interface CONTRACT.md documents for it -- `search_jql(jql, fields=...) ->
list[dict]` (Jira REST v3 issue-search shape: each dict has `key` and
`fields`) and `get_issue(key) -> dict` -- via the `JiraAdapterLike` Protocol
below, so it's fully testable today with a fake and needs no changes once
the real adapter lands. See NOTES.md.

## Output shape (what a Discord/Slack adapter consumes)

`run_standup()` returns a `StandupResult`: one `MemberUpdate` per roster
member with Jira activity in the queried window (drafted prose + structured
blocker flags + raw action-item candidate strings + any issue keys whose
text tripped the injection gate), a team-level prose roll-up, and
`action_item_proposals` -- the `Proposal` rows (already added to `session`,
not yet flushed/committed by this function) that
`meeting_action_items.propose_action_items()` built from every member's
flagged candidates, ready for the same confirm-card flow capability #3
uses. It's a plain `dataclasses`-based tree (`dataclasses.asdict()`-able,
`Proposal` rows aside) -- this module has no knowledge of Discord embeds or
Block Kit at all; posting is entirely another builder's job.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.capabilities._util import InjectionFlagged, gate_untrusted
from luna.capabilities.meeting_action_items import ActionItemCandidate, propose_action_items
from luna.db.models import Proposal, Roster
from luna.decision.engine import DecisionProvider, decide_many, decide_one
from luna.decision.schemas import NoulQuestion, ScoreQuestion
from luna.generation.generator import Generation
from luna.guardrails import untrusted

DEFAULT_LOOKBACK_DAYS = 7


class JiraAdapterLike(Protocol):
    async def search_jql(self, jql: str, fields: list[str] | None = None) -> list[dict]: ...

    async def get_issue(self, key: str) -> dict: ...


@dataclass
class BlockerFlag:
    issue_key: str
    reason_summary: str
    noul: float


@dataclass
class MemberUpdate:
    user_id: uuid.UUID
    name: str
    draft_text: str
    blockers: list[BlockerFlag] = field(default_factory=list)
    action_item_candidates: list[str] = field(default_factory=list)
    flagged_for_review: list[str] = field(default_factory=list)


@dataclass
class StandupResult:
    subteam: str | None  # None = whole-team
    generated_at: datetime
    member_updates: list[MemberUpdate]
    team_summary: str
    action_item_proposals: list[Proposal] = field(default_factory=list)


async def run_standup(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    generation: Generation,
    jira: JiraAdapterLike,
    *,
    subteam: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> StandupResult:
    result = await session.execute(select(Roster).where(Roster.licensed_bool.is_(True)))
    members = [m for m in result.scalars().all() if subteam is None or subteam in m.subteams]

    member_updates: list[MemberUpdate] = []
    for member in members:
        if not member.jira_account_id:
            continue  # unlicensed / no Jira identity -- nothing to poll
        member_updates.append(
            await _member_update(session, run_id, provider, generation, jira, member, lookback_days)
        )

    team_summary = await _team_summary(session, run_id, generation, subteam, member_updates)

    # spec §3.3#2: "#2 may create action-item proposals routed through #3's
    # confirm flow" -- one code path (meeting_action_items.propose_action_items)
    # turns a candidate string into a pending Proposal, whether the candidate
    # came from a meeting transcript or, as here, a standup ticket comment.
    candidates = [
        ActionItemCandidate(text=text, source=f"standup:{update.name}")
        for update in member_updates
        for text in update.action_item_candidates
    ]
    action_item_proposals = await propose_action_items(session, run_id, provider, candidates)

    return StandupResult(
        subteam=subteam,
        generated_at=datetime.now(),
        member_updates=member_updates,
        team_summary=team_summary,
        action_item_proposals=action_item_proposals,
    )


async def _member_update(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    generation: Generation,
    jira: JiraAdapterLike,
    member: Roster,
    lookback_days: int,
) -> MemberUpdate:
    jql = (
        f'assignee = "{member.jira_account_id}" AND updated >= -{lookback_days}d '
        "ORDER BY updated DESC"
    )
    issues = await jira.search_jql(jql, fields=["summary", "status", "comment", "updated"])

    update = MemberUpdate(user_id=member.user_id, name=member.name, draft_text="")
    untrusted_blocks = []

    for issue in issues:
        key = issue.get("key", "UNKNOWN")
        try:
            u = await gate_untrusted(session, run_id, provider, _issue_text(issue), source=f"jira:{key}")
        except InjectionFlagged:
            update.flagged_for_review.append(key)
            continue
        untrusted_blocks.append(u)

        answers = await decide_many(
            session,
            run_id,
            provider,
            u.value,
            {
                "blocker": NoulQuestion(
                    instructions=(
                        "Does this Jira issue's status/comments indicate it is currently "
                        "BLOCKED, or that it is blocking the team's progress on something else?"
                    ),
                ),
                "urgency": ScoreQuestion(
                    instructions="How urgent does this issue's recent activity sound?",
                    criteria=["low", "medium", "high", "critical"],
                ),
            },
        )
        blocker_answer = answers["blocker"]
        if blocker_answer.noul >= 0.5:  # type: ignore[union-attr]
            update.blockers.append(
                BlockerFlag(
                    issue_key=key,
                    reason_summary=_field_str(issue, "summary") or key,
                    noul=blocker_answer.noul,  # type: ignore[union-attr]
                )
            )

        action_answer = await decide_one(
            session,
            run_id,
            provider,
            u.value,
            "action_item",
            NoulQuestion(
                instructions=(
                    "Does this issue's recent activity mention a concrete follow-up task that "
                    "is NOT already tracked as its own Jira ticket (e.g. a comment like 'I'll "
                    "also need to file a ticket for...' or 'someone should look into...')? "
                    "Answer false if it's only describing work on this ticket itself."
                ),
            ),
        )
        if action_answer.noul >= 0.5:  # type: ignore[union-attr]
            update.action_item_candidates.append(f"{key}: {_field_str(issue, 'summary')}")

    if untrusted_blocks:
        update.draft_text = await generation.generate(
            instructions=(
                f"Write a concise (3-5 sentence) standup update draft for {member.name}, based "
                "on the Jira ticket activity below. This is a DRAFT the person will review and "
                "edit before it's posted -- state plainly what was worked on and note any "
                "blockers. Do not invent activity that isn't present in the tickets."
            ),
            untrusted=untrusted_blocks,
        )
    else:
        update.draft_text = f"No recent Jira activity found for {member.name} in the last {lookback_days} days."

    return update


async def _team_summary(
    session: AsyncSession,
    run_id: uuid.UUID,
    generation: Generation,
    subteam: str | None,
    member_updates: list[MemberUpdate],
) -> str:
    if not member_updates:
        return "No licensed roster members with recent Jira activity."

    blockers = [b for m in member_updates for b in m.blockers]
    combined = "\n\n".join(f"{m.name}: {m.draft_text}" for m in member_updates)
    label = subteam or "whole team"
    return await generation.generate(
        instructions=(
            f"Write a short (4-6 sentence) roll-up summary for the {label} standup, based on "
            f"the individual member updates below. Call out the {len(blockers)} flagged "
            "blocker(s) by ticket key if any are present. Do not invent details not present "
            "below."
        ),
        untrusted=untrusted(combined, source="standup:member_updates"),
    )


def _issue_text(issue: dict) -> str:
    fields = issue.get("fields", {}) or {}
    status = fields.get("status")
    status_name = status.get("name", "") if isinstance(status, dict) else (status or "")
    parts = [
        f"Key: {issue.get('key', '?')}",
        f"Summary: {fields.get('summary', '')}",
        f"Status: {status_name}",
    ]
    comments = fields.get("comment")
    if isinstance(comments, dict):
        for c in comments.get("comments", [])[-3:]:
            parts.append(f"Comment: {c.get('body', '')}")
    return "\n".join(parts)


def _field_str(issue: dict, name: str) -> str:
    return str((issue.get("fields", {}) or {}).get(name, ""))
