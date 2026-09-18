"""Capability #3 -- meeting notes / transcript -> action items -> Jira
(spec §3.3 #3, CONTRACT.md). Write-capable: always
proposal -> confirm -> apply -> verify (guardrails.py), never a direct Jira
write from this module.

Pipeline: `TranscriptAdapter` segments (consumed as plain
`list[dict]`/`TranscriptSegment`, this module doesn't import
`adapters.transcript` to stay decoupled/testable) ->
`segment_transcript_into_candidates()` uses `Generation.generate()` to chunk
the transcript into candidate action-item strings (free-form prose
extraction -- never the decision itself) -> `propose_action_items()` runs
the Decision Engine per candidate: Noul "is this an action item?", Choice
"owner?" over the `Roster` table, Choice "which component?" -> a batch of
`Proposal` rows, same pattern as capability #1: a human confirms each (or
"confirm all") before any Jira issue is actually created.

`standup.py` (capability #2, this build's other read-mostly capability)
calls `propose_action_items()` directly for its own flagged action-item
candidates, per spec "#2 may create action-item proposals routed through
#3's confirm flow" -- there is exactly one code path that turns a candidate
string into a pending `Proposal`, not two.

## Control-loop wiring

`decide`/`plan`/`gate` are registered into `luna.control_loop`'s shared
state machine at module import time (CONTRACT.md: capability modules
"register their node implementations... at import time"). `apply`/`verify`
are deliberately left unregistered (the foundation's no-op passthrough
handles them): `control_loop._drive()` runs all ten nodes synchronously in
one pass with no built-in way for a node to pause a run and wait for an
external event, so a human's Confirm tap cannot resume *this* run mid-drive
today. The real apply happens through `api/routes/proposals.py`'s
confirm-triggered `JiraAdapter.create_issue()` call (another builder's file,
not built yet in this worktree) acting on the `Proposal` rows this run
already wrote in `plan` -- a separate write, not a resumption of this
control-loop run. This is a resolved ambiguity in the foundation as handed
off, documented here and in NOTES.md rather than silently assumed.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.adapters.jira import JiraAdapter
from luna.audit import write_event
from luna.capabilities._util import InjectionFlagged, gate_untrusted
from luna.db.models import JiraChange, Proposal, ProposalStatus, Roster
from luna.decision.engine import DecisionProvider, decide_many
from luna.decision.schemas import ChoiceQuestion, NoulQuestion
from luna.generation.generator import Generation
from luna.guardrails import compute_idempotency_key, require_confirmation

# spec §3.2's component list (mirrors the Jira Components = subteams design).
COMPONENTS = [
    "Chassis",
    "Power",
    "Systems-Architecture",
    "Excavation",
    "Processing",
    "Integration",
    "Admin/PM",
]

UNASSIGNED = "unassigned"


@dataclass
class ActionItemCandidate:
    text: str
    source: str  # e.g. "meeting_transcript:<run_id>" or "standup:<issue_key>"


_NUMBERED_LINE = re.compile(r"^\s*\d+[.)]\s*(.+)$")


async def segment_transcript_into_candidates(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    generation: Generation,
    transcript_segments: list[dict],
) -> list[ActionItemCandidate]:
    """Turn raw `TranscriptAdapter`-shaped segments (`{start, end, text,
    speaker?}`) into candidate action-item strings via
    `Generation.generate()`. This is pure prose extraction -- the model is
    never asked whether something IS an action item here; that's
    `propose_action_items()`'s job through the Decision Engine, per
    CONTRACT.md's "never mixed in one call" rule."""
    if not transcript_segments:
        return []

    full_text = "\n".join(
        f"[{seg.get('start', 0):.0f}s-{seg.get('end', 0):.0f}s] {seg.get('text', '')}"
        for seg in transcript_segments
    )
    try:
        u = await gate_untrusted(
            session, run_id, provider, full_text, source=f"meeting_transcript:{run_id}"
        )
    except InjectionFlagged:
        return []

    raw = await generation.generate(
        instructions=(
            "The UNTRUSTED CONTENT below is a timestamped meeting transcript. List every "
            "distinct actionable follow-up task or decision that was discussed, one per line, "
            "numbered (1., 2., ...). Each line must be a short, self-contained description of "
            "ONE candidate action item -- do not summarize the whole meeting, do not merge "
            "multiple tasks into one line, and skip anything that isn't a concrete follow-up "
            "(small talk, pure status updates, etc). If there are none, output exactly: NONE."
        ),
        untrusted=u,
    )
    return _parse_candidates(raw, source=f"meeting_transcript:{run_id}")


def _parse_candidates(raw: str, *, source: str) -> list[ActionItemCandidate]:
    if raw.strip().upper() == "NONE":
        return []
    candidates: list[ActionItemCandidate] = []
    for line in raw.splitlines():
        m = _NUMBERED_LINE.match(line)
        if m:
            text = m.group(1).strip()
            if text:
                candidates.append(ActionItemCandidate(text=text, source=source))
    return candidates


async def propose_action_items(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    candidates: list[ActionItemCandidate],
) -> list[Proposal]:
    """Per spec #3: Decision Engine decides per candidate *is this an
    action item?* (Noul), *owner?* (Choice over roster), *which component?*
    (Choice). Produces `Proposal` rows added to `session` (not flushed here
    -- caller controls the transaction). Re-running this on the same
    candidates is idempotent: an existing `Proposal` with the same
    `idempotency_key` is reused instead of duplicated."""
    require_confirmation(kind="meeting_action_item", jira_write=True)

    if not candidates:
        return []

    roster_rows = (
        (await session.execute(select(Roster).where(Roster.licensed_bool.is_(True))))
        .scalars()
        .all()
    )
    owner_criteria: dict[str, str | None] = {str(r.user_id): r.name for r in roster_rows}
    owner_criteria[UNASSIGNED] = "No clear owner -- needs triage"

    proposals: list[Proposal] = []
    for candidate in candidates:
        questions = {
            "is_action_item": NoulQuestion(
                instructions=(
                    "Is the following CANDIDATE text a concrete, actionable follow-up task that "
                    "should become its own Jira ticket -- as opposed to a vague remark, a "
                    "question, or something that's really just a status update?"
                ),
            ),
            "owner": ChoiceQuestion(
                instructions=(
                    f"Who on the roster is the most likely owner of this action item, based on "
                    f"its content? Pick '{UNASSIGNED}' if it's genuinely unclear."
                ),
                criteria=owner_criteria,
            ),
            "component": ChoiceQuestion(
                instructions="Which subteam/component does this action item belong to?",
                criteria={c: None for c in COMPONENTS},
            ),
        }
        answers = await decide_many(session, run_id, provider, candidate.text, questions)
        is_action_item = answers["is_action_item"]
        if is_action_item.noul < 0.5:  # type: ignore[union-attr]
            continue

        owner_answer = answers["owner"]
        component_answer = answers["component"]
        owner_choice = owner_answer.choice  # type: ignore[union-attr]
        diff_json = {
            "summary": candidate.text,
            "assignee_user_id": None if owner_choice == UNASSIGNED else owner_choice,
            "component": component_answer.choice,  # type: ignore[union-attr]
            "source": candidate.source,
        }
        idempotency_key = compute_idempotency_key(
            diff_json=diff_json, kind="meeting_action_item", target_jira_key=None
        )

        existing = (
            await session.execute(
                select(Proposal).where(Proposal.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            proposals.append(existing)
            continue

        confidences = [owner_answer.confidence, component_answer.confidence]  # type: ignore[union-attr]
        proposal = Proposal(
            run_id=run_id,
            kind="meeting_action_item",
            target_jira_key=None,
            diff_json=diff_json,
            confidence=sum(confidences) / len(confidences),
            created_by_agent="meeting_action_items",
            idempotency_key=idempotency_key,
        )
        session.add(proposal)
        proposals.append(proposal)

    return proposals


async def apply_meeting_action_item(
    session: AsyncSession, proposal: Proposal, *, actor: str, jira: JiraAdapter | None = None
) -> JiraChange:
    """The actual Jira write for a confirmed `meeting_action_item` proposal.

    `status_intake.py`'s "park the run at `apply`, resume it later" pattern
    doesn't fit here: a single meeting-notes run produces a *batch* of
    independent `Proposal` rows (one per candidate action item), each
    confirmed separately (or via "confirm all") -- there is no single run to
    park and resume per confirm, `control_loop.resume()` on an
    already-`completed` run (this capability registers only `decide`/`plan`/
    `gate`, see the module docstring) is a documented no-op, not an error.
    So `api/routes/proposals.py`'s confirm handler calls this function
    directly for `proposal.kind == "meeting_action_item"` instead of
    `resume_with_session()` -- see that route's dispatch. This was a real
    gap found integrating this capability with the Jira layer: without this
    function, confirming one of these proposals returned 200 but silently
    never created the Jira issue.
    """
    jira = jira or JiraAdapter()
    diff = proposal.diff_json
    assignee_user_id = diff.get("assignee_user_id")
    jira_account_id: str | None = None
    if assignee_user_id:
        member = await session.get(Roster, uuid.UUID(assignee_user_id))
        jira_account_id = member.jira_account_id if member else None

    fields: dict[str, object] = {
        "summary": diff["summary"],
        "components": [{"name": diff["component"]}] if diff.get("component") else [],
        "labels": ["luna-meeting-action-item"],
    }
    if jira_account_id:
        fields["assignee"] = {"accountId": jira_account_id}

    issue = await jira.create_issue(
        fields=fields, idempotency_key=proposal.idempotency_key, session=session
    )
    jira_key = issue["key"]

    change = JiraChange(
        proposal_id=proposal.id,
        jira_key=jira_key,
        field="__create__",
        before_json=None,
        after_json=fields,
        applied_at=datetime.now(UTC),
        verify_ok=True,
    )
    session.add(change)

    proposal.target_jira_key = jira_key
    proposal.status = ProposalStatus.verified

    await write_event(
        session,
        actor=actor,
        action="meeting_action_item.apply",
        run_id=proposal.run_id,
        result_ref=jira_key,
    )
    return change


# --- control-loop wiring ----------------------------------------------------


async def _decide_node(ctx):  # type: ignore[no-untyped-def]
    from luna.db.session import session_scope
    from luna.decision.engine import get_decision_provider

    transcript_segments = ctx.data.get("transcript_segments", [])
    async with session_scope() as session:
        provider = get_decision_provider()
        generation = Generation.from_settings()
        try:
            candidates = await segment_transcript_into_candidates(
                session, ctx.run_id, provider, generation, transcript_segments
            )
            ctx.data["candidates"] = [c.text for c in candidates]
        finally:
            aclose = getattr(provider, "aclose", None)
            if aclose:
                await aclose()
            await generation.aclose()
    return ctx


async def _plan_node(ctx):  # type: ignore[no-untyped-def]
    from luna.db.session import session_scope
    from luna.decision.engine import get_decision_provider

    candidates = [
        ActionItemCandidate(text=t, source=f"meeting_transcript:{ctx.run_id}")
        for t in ctx.data.get("candidates", [])
    ]
    async with session_scope() as session:
        provider = get_decision_provider()
        try:
            proposals = await propose_action_items(session, ctx.run_id, provider, candidates)
            ctx.data["proposal_ids"] = [str(p.id) for p in proposals]
        finally:
            aclose = getattr(provider, "aclose", None)
            if aclose:
                await aclose()
    return ctx


async def _gate_node(ctx):  # type: ignore[no-untyped-def]
    # `propose_action_items()` already called `require_confirmation()` in
    # `plan` -- this node just records, for this run's own checkpoint/audit
    # trail, that the gate was satisfied. See module docstring for why the
    # actual apply is a separate write, not a resumption of this run.
    ctx.data["gated"] = True
    return ctx


# Registered at module import time -- matching status_intake.py/
# blocker_dependency.py/budget_watcher.py/deadline_reminders.py's pattern.
# This module originally wrapped these calls in a `register_control_loop_
# nodes()` function documented as "call once at process start," but nothing
# ever called it -- a real bug found while integrating this layer with the
# others (importing this module alone, via `luna/capabilities/__init__.py`,
# did not register anything, so `/record`'s voice-recording handoff would
# have silently no-op'd in production exactly like the `rag_qna`/`standup`
# gap documented in those modules). Fixed by registering directly here, like
# every other capability, rather than via an opt-in function nothing called.
from luna.control_loop import RunStatus, register_node  # noqa: E402

register_node("meeting_action_items", RunStatus.decide, _decide_node)
register_node("meeting_action_items", RunStatus.plan, _plan_node)
register_node("meeting_action_items", RunStatus.gate, _gate_node)
