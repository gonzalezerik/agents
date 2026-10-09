"""Capability #9 -- risk manager (R -> report; W via proposals). Not in the
original spec §3.3 list; added 2026-10-08 on top of the spec's existing
`Risk` issue type + `Risk Likelihood`/`Risk Impact`/`Risk Score` fields
(§3.2), which nothing else in LUNA acted on.

Two modes, one capability (`/risks` slash command, plus the scheduler):

1. **Review** (`/risks` with no text; `review()`; `workers/scheduler.py`).
   Read-only. Pulls every open `Risk` issue + the project's versions
   (milestone dates), then `_risk_math` does everything in code: L x I
   scoring and bands, the 5x5 matrix, a review checklist (unscored, score
   field out of sync, no owner, stale, HIGH without a linked mitigation,
   HIGH within 21 days of its milestone), per-milestone chance that a
   Major/Severe risk hits, and per-subteam exposure. No Decision Engine
   call -- there is no semantic judgment in arithmetic (same reasoning as
   `deadline_reminders.py`).

2. **Propose** (`/risks <notes>`; `propose_risks()`). Write-capable, always
   proposal -> confirm -> apply -> verify. The pasted notes go through the
   injection gate, `Generation` lists candidate risk statements (prose
   extraction only), then the Decision Engine answers typed questions per
   candidate: *is this a risk (uncertain future event) rather than an
   existing problem or a task?* (Noul), *which component?* (Choice),
   *likelihood?* / *impact?* (Score, 5 levels), *same risk as an existing
   one?* (Choice over open risk keys + `none`). The result is a `risk_new`
   or `risk_update` `Proposal`; `apply_risk_proposal()` is what
   `api/routes/proposals.py`'s confirm handler calls, then re-reads the
   issue to verify the fields landed.

## Custom field IDs are placeholders

Same situation as `budget_watcher.py`: `customfield_NNNNN` ids are assigned
by the real site when `seed/seed_jira.py` creates the fields. The defaults
below follow seed's creation order but are guesses until a site exists --
override via `custom_field_map` in `initial_data`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna import control_loop
from luna.adapters.jira import JiraAdapter
from luna.audit import write_event
from luna.capabilities import _risk_math as rm
from luna.capabilities._session import current_session, run_with_session
from luna.capabilities._util import InjectionFlagged, gate_untrusted
from luna.capabilities.meeting_action_items import COMPONENTS
from luna.control_loop import RunContext
from luna.db.models import JiraChange, Proposal, ProposalStatus, RunStatus
from luna.decision.engine import DecisionProvider, decide_many, get_decision_provider
from luna.decision.schemas import ChoiceQuestion, NoulQuestion, ScoreQuestion
from luna.generation.generator import Generation
from luna.guardrails import compute_idempotency_key, require_confirmation

CAPABILITY = "risk_manager"

DEFAULT_CUSTOM_FIELD_MAP: dict[str, str] = {
    "risk_likelihood": "customfield_10044",
    "risk_impact": "customfield_10045",
    "risk_score": "customfield_10046",
}
RISK_JQL = "project = {project} AND issuetype = Risk AND statusCategory != Done"
NO_DUPLICATE = "none"
MAX_CANDIDATES = 8

_NUMBERED_LINE = re.compile(r"^\s*\d+[.)]\s*(.+)$")


def _default_provider_factory() -> DecisionProvider:
    return get_decision_provider()


def _default_jira_factory() -> JiraAdapter:
    return JiraAdapter()


def _default_generation_factory() -> Generation:
    return Generation.from_settings()


_provider_factory: Callable[[], DecisionProvider] = _default_provider_factory
_jira_factory: Callable[[], JiraAdapter] = _default_jira_factory
_generation_factory: Callable[[], Generation] = _default_generation_factory


def _field_map(data: dict[str, Any]) -> dict[str, str]:
    return data.get("custom_field_map") or DEFAULT_CUSTOM_FIELD_MAP


def _notes(data: dict[str, Any]) -> str:
    """Discord sends `options.notes`; Slack sends the raw `options.text`."""
    options = (data.get("command") or {}).get("options") or {}
    return (options.get("notes") or options.get("text") or data.get("notes") or "").strip()


def _today(data: dict[str, Any]) -> date:
    raw = data.get("today")
    return date.fromisoformat(raw) if raw else datetime.now(UTC).date()


# --- review mode --------------------------------------------------------------


async def _retrieve(ctx: RunContext) -> RunContext:
    if "issues" in ctx.data and "versions" in ctx.data:
        return ctx  # test/caller-supplied data bypasses the Jira calls

    field_map = _field_map(ctx.data)
    project = ctx.data.get("project_key", "C3")
    jira = _jira_factory()
    try:
        resp = await jira.search_jql(
            RISK_JQL.format(project=project),
            fields=[
                "summary",
                "status",
                "components",
                "assignee",
                "updated",
                "fixVersions",
                "issuelinks",
                *field_map.values(),
            ],
            max_results=200,
        )
        versions = await jira.list_versions(project)
    finally:
        await jira.aclose()
    ctx.data["issues"] = resp.get("issues", [])
    ctx.data["versions"] = versions
    return ctx


def build_review(data: dict[str, Any]) -> dict[str, Any]:
    """Everything the review reports, as JSON-serializable data (it lands in
    `agent_run.checkpoint_json`)."""
    field_map = _field_map(data)
    today = _today(data)
    risks = [rm.parse_risk_issue(i, field_map) for i in data.get("issues", [])]
    milestone_dates = {
        v["name"]: date.fromisoformat(v["releaseDate"])
        for v in data.get("versions", [])
        if v.get("releaseDate") and not v.get("released")
    }
    findings = rm.review(risks, today=today, milestone_dates=milestone_dates)
    outlook = rm.milestone_outlook(risks, milestone_dates, today=today)
    exposure = rm.subteam_exposure(risks)
    return {
        "risks": [
            {
                "key": r.key,
                "summary": r.summary,
                "likelihood": r.likelihood,
                "impact": r.impact,
                "score": r.score,
                "level": rm.level(r.score) if r.score is not None else None,
                "components": r.components,
                "assignee": r.assignee,
            }
            for r in risks
        ],
        "findings": [f.__dict__ for f in findings],
        "milestones": outlook,
        "exposure": exposure,
        "summary_markdown": rm.render_report(risks, findings, outlook, exposure),
    }


# --- propose mode ---------------------------------------------------------------


def _parse_candidates(raw: str) -> list[str]:
    if raw.strip().upper() == "NONE":
        return []
    out = []
    for line in raw.splitlines():
        m = _NUMBERED_LINE.match(line)
        if m and m.group(1).strip():
            out.append(m.group(1).strip())
    return out[:MAX_CANDIDATES]


async def propose_risks(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    generation: Generation,
    notes: str,
    *,
    existing: list[rm.RiskItem],
    source: str,
) -> list[Proposal]:
    """Notes -> pending `risk_new`/`risk_update` proposals. Never writes Jira.
    Re-running on the same notes reuses proposals by idempotency key."""
    require_confirmation(kind="risk_new", jira_write=True)
    if not notes:
        return []
    try:
        u = await gate_untrusted(session, run_id, provider, notes, source=source)
    except InjectionFlagged:
        return []

    raw = await generation.generate(
        instructions=(
            "The UNTRUSTED CONTENT below is notes from a lunar rover student engineering team. "
            "List every distinct project RISK it mentions or implies: an uncertain future event "
            "that would hurt the rover, schedule, budget, or safety if it happened. Write each "
            "one as a single line in the form 'Given <condition>, there is a possibility that "
            "<consequence>', numbered (1., 2., ...). Do not list tasks, decisions, or problems "
            "that have already happened. If there are none, output exactly: NONE."
        ),
        untrusted=u,
    )

    open_by_key = {r.key: r for r in existing}
    dup_criteria: dict[str, str | None] = {r.key: r.summary for r in existing}
    dup_criteria[NO_DUPLICATE] = "Not the same as any existing risk"

    proposals: list[Proposal] = []
    for statement in _parse_candidates(raw):
        questions: dict[str, Any] = {
            "is_risk": NoulQuestion(
                instructions=(
                    "Is this CANDIDATE a genuine project risk -- an uncertain future event with a "
                    "negative consequence -- rather than a problem that already happened, a task, "
                    "or a vague remark?"
                )
            ),
            "component": ChoiceQuestion(
                instructions="Which subteam/component owns this risk?",
                criteria={c: None for c in COMPONENTS},
            ),
            "likelihood": ScoreQuestion(
                instructions="How likely is this risk to occur before the next competition milestone?",
                criteria=rm.LIKELIHOOD_LABELS,
            ),
            "impact": ScoreQuestion(
                instructions="If this risk occurs, how bad is the impact on the team and rover?",
                criteria=rm.IMPACT_LABELS,
            ),
        }
        if existing:
            questions["duplicate_of"] = ChoiceQuestion(
                instructions=(
                    "Is this CANDIDATE essentially the same risk as one already in the register? "
                    f"Pick its key, or '{NO_DUPLICATE}'."
                ),
                criteria=dup_criteria,
            )
        answers = await decide_many(session, run_id, provider, statement, questions)
        if answers["is_risk"].noul < 0.5:  # type: ignore[union-attr]
            continue

        likelihood = rm.level_from_score_answer(answers["likelihood"].score)  # type: ignore[union-attr]
        impact = rm.level_from_score_answer(answers["impact"].score)  # type: ignore[union-attr]
        component = answers["component"].choice  # type: ignore[union-attr]
        dup = answers.get("duplicate_of")
        target = dup.choice if dup is not None and dup.choice != NO_DUPLICATE else None  # type: ignore[union-attr]

        if target is not None:
            prior = open_by_key[target]
            if (prior.likelihood, prior.impact) == (likelihood, impact):
                continue  # same risk, same assessment: nothing to propose
            kind = "risk_update"
            diff_json: dict[str, Any] = {
                "likelihood": {"before": prior.likelihood, "after": likelihood},
                "impact": {"before": prior.impact, "after": impact},
                "evidence": statement,
                "source": source,
            }
        else:
            kind = "risk_new"
            diff_json = {
                "summary": statement[:250],
                "statement": statement,
                "component": component,
                "likelihood": likelihood,
                "impact": impact,
                "score": likelihood * impact,
                "level": rm.level(likelihood * impact),
                "source": source,
            }

        # `source` carries the run id; leave it out so re-pasting the same
        # notes in a new run reuses the pending proposal instead of duplicating it.
        idempotency_key = compute_idempotency_key(
            diff_json={k: v for k, v in diff_json.items() if k != "source"},
            kind=kind,
            target_jira_key=target,
        )
        existing_row = (
            await session.execute(
                select(Proposal).where(Proposal.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing_row is not None:
            proposals.append(existing_row)
            continue

        confidences = [
            answers[q].confidence  # type: ignore[union-attr]
            for q in ("component", "likelihood", "impact", "duplicate_of")
            if q in answers
        ]
        proposal = Proposal(
            run_id=run_id,
            kind=kind,
            target_jira_key=target,
            diff_json=diff_json,
            confidence=sum(confidences) / len(confidences),
            created_by_agent=CAPABILITY,
            idempotency_key=idempotency_key,
        )
        session.add(proposal)
        proposals.append(proposal)
    return proposals


def _adf(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def apply_risk_proposal(
    session: AsyncSession,
    proposal: Proposal,
    *,
    actor: str,
    jira: JiraAdapter | None = None,
    project_key: str = "C3",
    custom_field_map: dict[str, str] | None = None,
) -> JiraChange:
    """The Jira write for a confirmed `risk_new`/`risk_update` proposal,
    followed by a re-read that checks Likelihood/Impact/Score landed.
    Dispatched from `api/routes/proposals.py`, like
    `apply_meeting_action_item()`."""
    jira = jira or JiraAdapter()
    fmap = custom_field_map or DEFAULT_CUSTOM_FIELD_MAP
    diff = proposal.diff_json

    if proposal.kind == "risk_new":
        lik, imp = diff["likelihood"], diff["impact"]
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "issuetype": {"name": "Risk"},
            "summary": diff["summary"],
            "description": _adf(f"{diff['statement']}\n\nProposed by LUNA from {diff['source']}."),
            "components": [{"name": diff["component"]}],
            "labels": ["luna-risk"],
        }
        before = None
        issue = await jira.create_issue(
            fields={
                **fields,
                fmap["risk_likelihood"]: lik,
                fmap["risk_impact"]: imp,
                fmap["risk_score"]: lik * imp,
            },
            idempotency_key=proposal.idempotency_key,
            session=session,
        )
        key = issue["key"]
        field_name = "__create__"
    else:
        key = proposal.target_jira_key
        lik, imp = diff["likelihood"]["after"], diff["impact"]["after"]
        before = {"likelihood": diff["likelihood"]["before"], "impact": diff["impact"]["before"]}
        await jira.update_fields(
            key,
            {fmap["risk_likelihood"]: lik, fmap["risk_impact"]: imp, fmap["risk_score"]: lik * imp},
            idempotency_key=proposal.idempotency_key,
            session=session,
        )
        await jira.add_comment(
            key,
            f"LUNA reassessed this risk as L{lik} x I{imp} = {lik * imp} "
            f"({rm.level(lik * imp)}), confirmed by {actor}. Evidence: {diff['evidence']}",
            idempotency_key=proposal.idempotency_key + ":comment",
            session=session,
        )
        field_name = "risk_assessment"

    reread = await jira.get_issue(key, fields=list(fmap.values()))
    got = reread.get("fields", {})
    verify_ok = (
        rm._as_level(got.get(fmap["risk_likelihood"])) == lik
        and rm._as_level(got.get(fmap["risk_impact"])) == imp
    )

    change = JiraChange(
        proposal_id=proposal.id,
        jira_key=key,
        field=field_name,
        before_json=before,
        after_json={"likelihood": lik, "impact": imp, "score": lik * imp},
        applied_at=datetime.now(UTC),
        verify_ok=verify_ok,
    )
    session.add(change)
    proposal.target_jira_key = key
    proposal.status = ProposalStatus.verified if verify_ok else ProposalStatus.failed
    await write_event(
        session,
        actor=actor,
        action=f"{proposal.kind}.apply",
        run_id=proposal.run_id,
        result_ref=f"{key} verify_ok={verify_ok}",
    )
    return change


# --- control-loop wiring ----------------------------------------------------------


async def _decide(ctx: RunContext) -> RunContext:
    notes = _notes(ctx.data)
    if not notes:
        ctx.data.update(build_review(ctx.data))
        return ctx

    session = current_session()
    provider = _provider_factory()
    generation = _generation_factory()
    field_map = _field_map(ctx.data)
    existing = [rm.parse_risk_issue(i, field_map) for i in ctx.data.get("issues", [])]
    try:
        proposals = await propose_risks(
            session,
            ctx.run_id,
            provider,
            generation,
            notes,
            existing=existing,
            source=f"risks_command:{ctx.run_id}",
        )
        await session.flush()
    finally:
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await aclose()
        await generation.aclose()
    ctx.data["proposal_ids"] = [str(p.id) for p in proposals]
    ctx.data["summary_markdown"] = (
        f"Drafted {len(proposals)} risk proposal(s) for review -- nothing is in Jira until "
        "someone confirms each card."
        if proposals
        else "No new or changed risks found in those notes."
    )
    return ctx


async def _respond(ctx: RunContext) -> RunContext:
    session = current_session()
    if "proposal_ids" in ctx.data:
        ref = f"{len(ctx.data['proposal_ids'])} proposal(s)"
    else:
        ref = f"{len(ctx.data.get('risks', []))} risk(s), {len(ctx.data.get('findings', []))} finding(s)"
    await write_event(
        session, actor=CAPABILITY, action="respond.risk_manager", run_id=ctx.run_id, result_ref=ref
    )
    return ctx


control_loop.register_node(CAPABILITY, RunStatus.retrieve, _retrieve)
control_loop.register_node(CAPABILITY, RunStatus.decide, _decide)
control_loop.register_node(CAPABILITY, RunStatus.respond, _respond)


async def review(
    session: AsyncSession, *, project_key: str = "C3", trigger_source: str = "scheduler"
) -> RunContext:
    """Run the read-only risk review once (`.data["summary_markdown"]`,
    `["findings"]`, `["milestones"]`, `["exposure"]`)."""
    return await run_with_session(
        session,
        capability=CAPABILITY,
        trigger_source=trigger_source,
        initial_data={"project_key": project_key},
    )
