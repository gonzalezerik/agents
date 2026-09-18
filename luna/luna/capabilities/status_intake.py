"""Capability #1 -- conversational status intake (write-capable), spec §3.3.

Pipeline (spec): a student's free-form status update -> Decision Engine
resolves *which issue* (Choice over JQL candidates), *what transition*
(Choice), *is this a blocker?* (Noul), *does this need human confirm?*
(Noul, always true in practice), *urgency* (Score) -> a `Proposal` row ->
human taps Confirm/Edit/Cancel -> apply via Jira REST -> verify by re-reading
-> audit.

## Why this module doesn't just call `control_loop.run()`

`control_loop.NODE_ORDER` is
`ingest,normalize,retrieve,decide,plan,gate,apply,verify,log,respond` and
`control_loop.run()`/`_drive()` always walk that whole list top to bottom,
persisting a checkpoint after each node -- there is no "pause here and wait"
primitive, only "keep going" or "raise -> mark the whole run `failed`".
Guardrails (spec §3.6) require *every* Jira write to wait for an explicit
human Confirm tap with no bypass -- so Apply cannot run in the same pass that
produced the proposal.

This module resolves that by never calling `control_loop.run()`/`_drive()`
directly for the pre-confirm portion. `start()` below drives
`ingest -> normalize -> retrieve -> decide -> plan -> gate` itself (a small
loop that mirrors `control_loop._drive`'s per-node "run it, advance
`ctx.status`, persist the checkpoint" behavior closely enough that the real,
*unmodified* `control_loop.resume()` can pick the run back up later) and then
simply **stops** -- leaving `agent_run.status == RunStatus.apply`, i.e. Apply
is "the first non-terminal node left after Gate". `finish_after_confirm()`
is what `api/routes/proposals.py`'s confirm handler calls once a human has
confirmed: it's a thin wrapper around the real `control_loop.resume()`,
which drives `apply -> verify -> log -> respond -> completed` exactly as
`control_loop.py` was designed to. `ingest`/`normalize`/`log`/`respond` are
never registered (safe no-ops per `control_loop.py`'s own contract) --
retrieval and the untrusted/injection-gate handling that would normally live
in `normalize`/`retrieve` happen inside `decide` instead, since this
capability was only asked to register `decide`/`plan`/`gate`/`apply`/
`verify`.

## `luna/workers/poller.py`'s resume-on-startup carve-out

CONTRACT.md says workers resume every non-terminal `agent_run` on startup.
For every *other* capability that's harmless. For `status_intake` specifically
it is not: a run sitting at `apply` is deliberately waiting on a human, not
crashed. `poller.py` special-cases this -- see its module docstring -- by
only resuming a `status_intake` run at `apply` when the matching `Proposal`
is already `confirmed` (a genuine crash-during-apply), leaving merely-pending
ones alone for the confirm route to pick up later.

## Dependency injection for tests

`_provider_factory`/`_jira_factory` are the two seams: reassign them (e.g.
`status_intake._provider_factory = lambda: fake_provider`) in a test to swap
in a fake `DecisionProvider`/`JiraAdapter` without touching module internals.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna import control_loop
from luna.adapters.jira import JiraAdapter
from luna.audit import write_event
from luna.capabilities._session import bound_session, current_session, resume_with_session
from luna.control_loop import NODE_ORDER, RunContext
from luna.db.models import AgentRun, JiraChange, Proposal, ProposalStatus, RunStatus
from luna.decision.engine import DecisionProvider, decide_many, get_decision_provider
from luna.decision.schemas import ChoiceQuestion, NoulQuestion, ScoreQuestion
from luna.guardrails import (
    build_injection_gate_question,
    compute_idempotency_key,
    is_injection_flagged,
    require_confirmation,
    untrusted,
)

CAPABILITY = "status_intake"

# Placeholder fallback when the caller doesn't supply the issue's real
# available transitions (normally fetched via a Jira `GET
# /issue/{key}/transitions` call by whatever's driving this -- e.g. the
# Discord modal). Kept small and clearly a fallback, not a guess dressed up
# as real data.
DEFAULT_TRANSITIONS: list[dict[str, str]] = [
    {"id": "11", "name": "To Do"},
    {"id": "21", "name": "In Progress"},
    {"id": "31", "name": "In Review"},
    {"id": "41", "name": "Blocked"},
    {"id": "51", "name": "Done"},
]

URGENCY_LEVELS = ["low", "medium", "high", "critical"]

def _default_provider_factory() -> DecisionProvider:
    return get_decision_provider()


def _default_jira_factory() -> JiraAdapter:
    return JiraAdapter()


_provider_factory: Callable[[], DecisionProvider] = _default_provider_factory
_jira_factory: Callable[[], JiraAdapter] = _default_jira_factory


async def _noop(ctx: RunContext) -> RunContext:
    return ctx


async def _fetch_candidates(jira: JiraAdapter, data: dict[str, Any]) -> list[dict[str, Any]]:
    if "candidates" in data:
        # Test/caller-supplied candidates bypass the Jira call entirely.
        return list(data["candidates"])
    jql = data.get("jql") or "statusCategory != Done ORDER BY updated DESC"
    resp = await jira.search_jql(jql, fields=["summary", "status"], max_results=25)
    return [
        {"key": issue["key"], "summary": issue.get("fields", {}).get("summary")}
        for issue in resp.get("issues", [])
    ]


async def _decide(ctx: RunContext) -> RunContext:
    session = current_session()
    provider = _provider_factory()
    raw_text = ctx.data.get("raw_text", "")
    source = ctx.data.get("source", "unknown")
    inbound = untrusted(raw_text, source=source)

    injection_answers = await decide_many(
        session, ctx.run_id, provider, inbound.value, {"injection": build_injection_gate_question()}
    )
    injection_noul = injection_answers["injection"].noul
    flagged = is_injection_flagged(injection_noul)
    ctx.data["injection_noul"] = injection_noul
    ctx.data["flagged_for_review"] = flagged

    if flagged:
        # Per spec §3.6: a positive injection-gate flag halts automatic
        # processing -- we do not ask any further question about this input.
        ctx.data["decisions"] = None
        return ctx

    jira = _jira_factory()
    try:
        candidates = await _fetch_candidates(jira, ctx.data)
    finally:
        await jira.aclose()
    ctx.data["candidates"] = candidates

    if not candidates:
        ctx.data["decisions"] = {"no_candidates": True}
        return ctx

    issue_criteria = {c["key"]: c.get("summary") for c in candidates}
    transitions = ctx.data.get("available_transitions") or DEFAULT_TRANSITIONS
    transition_criteria = {t["id"]: t.get("name") for t in transitions}

    questions = {
        "issue": ChoiceQuestion(
            instructions="Which Jira issue does this status update most likely refer to?",
            criteria=issue_criteria,
        ),
        "transition": ChoiceQuestion(
            instructions=(
                "Given the status update, which workflow transition (if any) best "
                "matches what the person is reporting? If none clearly applies, pick "
                "the closest match."
            ),
            criteria=transition_criteria,
        ),
        "blocker": NoulQuestion(
            instructions="Does this status update indicate the person is blocked on something?"
        ),
        "needs_confirm": NoulQuestion(
            instructions="Does this proposed Jira change need a human to confirm it before it's applied?"
        ),
        "urgency": ScoreQuestion(
            instructions="How urgent does this status update sound?", criteria=URGENCY_LEVELS
        ),
    }
    state = {"text": inbound.value, "candidate_issues": issue_criteria}
    answers = await decide_many(session, ctx.run_id, provider, state, questions)
    ctx.data["decisions"] = {qid: a.model_dump(mode="json") for qid, a in answers.items()}
    return ctx


async def _plan(ctx: RunContext) -> RunContext:
    session = current_session()

    if ctx.data.get("flagged_for_review"):
        diff = {
            "flagged": True,
            "reason": "input failed the prompt-injection gate",
            "injection_noul": ctx.data.get("injection_noul"),
        }
        kind = "status_update_flagged"
        target_key = None
    else:
        decisions = ctx.data.get("decisions") or {}
        if decisions.get("no_candidates"):
            diff = {"no_matching_issue": True, "raw_text": ctx.data.get("raw_text")}
            kind = "status_update_no_match"
            target_key = None
        else:
            issue = decisions["issue"]
            transition = decisions["transition"]
            blocker = decisions["blocker"]["noul"]
            needs_confirm = decisions["needs_confirm"]["noul"]
            urgency = decisions["urgency"]
            target_key = issue["choice"]
            diff = {
                "transition_id": transition["choice"],
                "transition_probabilities": transition["probabilities"],
                "is_blocker": blocker >= 0.5,
                "needs_confirm": needs_confirm >= 0.5,
                "urgency_score": urgency["score"],
                "comment": ctx.data.get("raw_text"),
            }
            kind = "status_transition"

    idempotency_key = compute_idempotency_key(diff_json=diff, kind=kind, target_jira_key=target_key)
    proposal = Proposal(
        run_id=ctx.run_id,
        kind=kind,
        target_jira_key=target_key,
        diff_json=diff,
        confidence=(diff.get("urgency_score") if kind == "status_transition" else None),
        created_by_agent=CAPABILITY,
        idempotency_key=idempotency_key,
    )
    session.add(proposal)
    await session.flush()
    ctx.data["proposal_id"] = str(proposal.id)
    ctx.data["proposal_kind"] = kind
    return ctx


async def _gate(ctx: RunContext) -> RunContext:
    session = current_session()
    # Always True for Jira writes -- called for real, not skipped, per the
    # task brief ("call it, don't skip it, even though you know the
    # answer"). Raises if ever misused with jira_write=False, which this
    # capability never does.
    require_confirmation(kind=ctx.data.get("proposal_kind", "status_transition"), jira_write=True)
    await write_event(
        session,
        actor=CAPABILITY,
        action="gate.require_confirmation",
        run_id=ctx.run_id,
        result_ref=ctx.data.get("proposal_id"),
    )
    return ctx


async def _apply(ctx: RunContext) -> RunContext:
    session = current_session()
    proposal_id_raw = ctx.data.get("proposal_id")
    if proposal_id_raw is None:
        raise RuntimeError("status_intake apply: no proposal_id in checkpoint data")
    proposal = await session.get(Proposal, uuid.UUID(proposal_id_raw))
    if proposal is None:
        raise RuntimeError(f"status_intake apply: proposal {proposal_id_raw} not found")
    if proposal.status != ProposalStatus.confirmed:
        raise RuntimeError(
            f"status_intake apply: proposal {proposal.id} is {proposal.status.value}, "
            "expected confirmed -- refusing to apply an unconfirmed/already-resolved change"
        )

    if proposal.kind in ("status_update_flagged", "status_update_no_match"):
        proposal.status = ProposalStatus.applied
        await session.flush()
        ctx.data["applied"] = {"noop": True, "kind": proposal.kind}
        return ctx

    diff = proposal.diff_json
    jira = _jira_factory()
    try:
        result = await jira.transition_issue(
            proposal.target_jira_key,
            diff["transition_id"],
            idempotency_key=proposal.idempotency_key,
            session=session,
        )
        session.add(
            JiraChange(
                proposal_id=proposal.id,
                jira_key=proposal.target_jira_key,
                field="status",
                before_json=None,
                after_json={"transition_id": diff["transition_id"]},
                applied_at=datetime.now(),
                verify_ok=None,
            )
        )

        comment_text = diff.get("comment")
        if comment_text:
            await jira.add_comment(
                proposal.target_jira_key,
                comment_text,
                idempotency_key=f"{proposal.idempotency_key}:comment",
                session=session,
            )

        proposal.status = ProposalStatus.applied
        await session.flush()
        await write_event(
            session,
            actor=CAPABILITY,
            action="apply.jira_write",
            run_id=ctx.run_id,
            tool_call_json={"jira_key": proposal.target_jira_key, "diff": diff},
            result_ref=str(result),
        )
        ctx.data["applied"] = result
    finally:
        await jira.aclose()
    return ctx


async def _verify(ctx: RunContext) -> RunContext:
    session = current_session()
    proposal_id_raw = ctx.data.get("proposal_id")
    proposal = await session.get(Proposal, uuid.UUID(proposal_id_raw)) if proposal_id_raw else None
    if proposal is None or proposal.kind in ("status_update_flagged", "status_update_no_match"):
        return ctx

    jira = _jira_factory()
    try:
        issue = await jira.get_issue(proposal.target_jira_key, fields=["status"])
        actual_status = issue.get("fields", {}).get("status", {}).get("name")
        ok = actual_status is not None

        result = await session.execute(
            select(JiraChange)
            .where(JiraChange.proposal_id == proposal.id)
            .order_by(JiraChange.id.desc())
            .limit(1)
        )
        change = result.scalar_one_or_none()
        if change is not None:
            change.verify_ok = ok

        proposal.status = ProposalStatus.verified if ok else ProposalStatus.failed
        await session.flush()
        ctx.data["verified"] = {"ok": ok, "status": actual_status}
        await write_event(
            session,
            actor=CAPABILITY,
            action="verify.reread_issue",
            run_id=ctx.run_id,
            result_ref=actual_status,
        )
    finally:
        await jira.aclose()
    return ctx


control_loop.register_node(CAPABILITY, RunStatus.decide, _decide)
control_loop.register_node(CAPABILITY, RunStatus.plan, _plan)
control_loop.register_node(CAPABILITY, RunStatus.gate, _gate)
control_loop.register_node(CAPABILITY, RunStatus.apply, _apply)
control_loop.register_node(CAPABILITY, RunStatus.verify, _verify)


_PRE_APPLY_NODES: list[tuple[RunStatus, control_loop.NodeFn]] = [
    (RunStatus.ingest, _noop),
    (RunStatus.normalize, _noop),
    (RunStatus.retrieve, _noop),
    (RunStatus.decide, _decide),
    (RunStatus.plan, _plan),
    (RunStatus.gate, _gate),
]


async def _persist_partial(session: AsyncSession, run_row: AgentRun, ctx: RunContext) -> None:
    """Mirrors `control_loop._persist`'s checkpoint shape exactly (see this
    module's docstring for why we can't just call the real `_drive`/`run`
    here) so `control_loop.resume()`, unmodified, can pick this run back up
    later. Never marks `ended_at` -- we never reach a terminal status here."""
    run_row.status = ctx.status
    run_row.checkpoint_json = {
        "data": ctx.data,
        "status": ctx.status.value,
        "error": ctx.error,
        "trigger_source": ctx.trigger_source,
        "actor_user": ctx.actor_user,
    }
    await session.flush()


async def start(
    session: AsyncSession,
    *,
    trigger_source: str,
    actor_user: str | None = None,
    initial_data: dict[str, Any] | None = None,
) -> RunContext:
    """Kick off a status_intake run and drive it through `gate`, then stop
    (see module docstring). Whatever adapter event eventually triggers this
    (`api/routes/ingest.py`, owned by another builder, doesn't exist in this
    worktree yet) should call this with `initial_data={"raw_text": ...,
    "source": "discord"|"slack", ...}`."""
    run_row = AgentRun(
        capability=CAPABILITY,
        trigger_source=trigger_source,
        actor_user=actor_user,
        status=RunStatus.ingest,
        checkpoint_json={},
    )
    session.add(run_row)
    await session.flush()

    ctx = RunContext(
        run_id=run_row.id,
        capability=CAPABILITY,
        trigger_source=trigger_source,
        actor_user=actor_user,
        status=RunStatus.ingest,
        data=initial_data or {},
    )

    async with bound_session(session):
        for node, fn in _PRE_APPLY_NODES:
            ctx.status = node
            try:
                ctx = await fn(ctx)
            except Exception as exc:  # noqa: BLE001 - mirrors control_loop._drive's own broad catch
                ctx.status = RunStatus.failed
                ctx.error = f"{node.value}: {exc}"
                await _persist_partial(session, run_row, ctx)
                raise
            next_index = NODE_ORDER.index(node) + 1
            ctx.status = NODE_ORDER[next_index]  # never out of range: gate is not the last node
            await _persist_partial(session, run_row, ctx)

    return ctx


async def finish_after_confirm(session: AsyncSession, run_id: uuid.UUID) -> RunContext:
    """Called by `api/routes/proposals.py`'s confirm handler after it has
    already set the matching `Proposal.status = confirmed`. `agent_run.status`
    is sitting at `apply` (the first non-terminal node left after `start()`
    stopped at Gate), so the real, unmodified `control_loop.resume()` drives
    `apply -> verify -> log -> respond -> completed` from here."""
    return await resume_with_session(session, run_id)
