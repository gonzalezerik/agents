"""`POST /proposals/{id}/confirm`, `/cancel`, `/edit`.

The one human-in-the-loop surface guardrails.py requires for every
Jira write -- see `luna/capabilities/status_intake.py`'s module docstring for
how a `Proposal` reaching here connects back to its `agent_run`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from luna.api.deps import get_db, require_service_token
from luna.audit import write_event
from luna.capabilities._session import resume_with_session
from luna.control_loop import TERMINAL_STATUSES
from luna.db.models import AgentRun, Proposal, ProposalStatus
from luna.guardrails import compute_idempotency_key

router = APIRouter(prefix="/proposals", tags=["proposals"], dependencies=[Depends(require_service_token)])


class ProposalOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    kind: str
    target_jira_key: str | None
    diff_json: dict[str, Any]
    confidence: float | None
    status: str
    created_by_agent: str
    confirmed_by_user: str | None
    idempotency_key: str

    model_config = {"from_attributes": True}


class ConfirmBody(BaseModel):
    actor: str


class CancelBody(BaseModel):
    actor: str


class EditBody(BaseModel):
    actor: str
    diff_patch: dict[str, Any]
    target_jira_key: str | None = None


async def _get_proposal_or_404(session: AsyncSession, proposal_id: uuid.UUID) -> Proposal:
    proposal = await session.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="proposal not found")
    return proposal


def _require_status(proposal: Proposal, expected: ProposalStatus) -> None:
    if proposal.status != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"proposal {proposal.id} is {proposal.status.value}, expected {expected.value}",
        )


async def _apply_confirmed_proposal(session: AsyncSession, proposal: Proposal, *, actor: str) -> None:
    """Dispatches by `proposal.kind` to whichever apply strategy that
    capability actually uses.

    `status_intake`'s `"status_transition"` kind (and any future capability
    using the same pattern) parks its *entire* `agent_run` at
    `RunStatus.apply` after `gate` and expects `control_loop.resume()` to
    finish it -- see `capabilities/status_intake.py`'s module docstring.
    `meeting_action_items`'s `"meeting_action_item"` kind does not fit that
    shape: one run's `plan` step can write a *batch* of independent
    proposals (one per transcript candidate), each confirmed separately (or
    via "confirm all"), and that run already reached `completed` right after
    `gate` (the capability registers only `decide`/`plan`/`gate` -- see its
    module docstring on why). `control_loop.resume()` on an already-terminal
    run is a documented no-op, not an error, so calling it here for this
    kind would return 200 without ever creating the Jira issue -- a real
    integration gap found wiring this capability to this route, fixed by
    dispatching to its own `apply_meeting_action_item()` instead. Add a new
    branch here for any future capability whose proposals don't fit
    `status_intake`'s single-proposal-per-run shape."""
    if proposal.kind == "meeting_action_item":
        from luna.capabilities.meeting_action_items import apply_meeting_action_item

        await apply_meeting_action_item(session, proposal, actor=actor)
        return
    if proposal.kind in ("risk_new", "risk_update"):
        from luna.capabilities.risk_manager import apply_risk_proposal

        await apply_risk_proposal(session, proposal, actor=actor)
        return
    await resume_with_session(session, proposal.run_id)


@router.post("/{proposal_id}/confirm", response_model=ProposalOut)
async def confirm_proposal(
    proposal_id: uuid.UUID, body: ConfirmBody, session: AsyncSession = Depends(get_db)
) -> Proposal:
    """Sets `Proposal.status = confirmed`, then applies it via
    `_apply_confirmed_proposal()` (dispatched by `proposal.kind` -- see that
    function's docstring for why this isn't a single uniform
    `control_loop.resume()` call). If the apply raises, the partial-failure
    checkpoint that `control_loop`'s own exception handling already flushed
    (for the `resume()` path) is committed before the error is surfaced, so
    the `agent_run`/`proposal` rows reflect reality rather than silently
    rolling back a real (attempted) Jira write record."""
    proposal = await _get_proposal_or_404(session, proposal_id)
    _require_status(proposal, ProposalStatus.pending)

    proposal.status = ProposalStatus.confirmed
    proposal.confirmed_by_user = body.actor
    await session.flush()
    await write_event(
        session,
        actor=body.actor,
        action="proposal.confirm",
        run_id=proposal.run_id,
        result_ref=str(proposal.id),
    )

    try:
        await _apply_confirmed_proposal(session, proposal, actor=body.actor)
    except Exception as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"proposal {proposal.id} confirmed but apply failed: {exc}",
        ) from exc

    await session.commit()
    await session.refresh(proposal)
    return proposal


@router.post("/{proposal_id}/cancel", response_model=ProposalOut)
async def cancel_proposal(
    proposal_id: uuid.UUID, body: CancelBody, session: AsyncSession = Depends(get_db)
) -> Proposal:
    """Only a still-`pending` proposal can be cancelled. Also marks the
    owning `agent_run` cancelled directly (control_loop.py has no "cancel a
    run" primitive of its own -- this is a plain row update, not a
    control_loop-driven transition) so it stops showing up as a non-terminal
    run for `workers/poller.py`'s startup resume scan."""
    proposal = await _get_proposal_or_404(session, proposal_id)
    _require_status(proposal, ProposalStatus.pending)

    proposal.status = ProposalStatus.cancelled
    run = await session.get(AgentRun, proposal.run_id)
    if run is not None and run.status not in TERMINAL_STATUSES:
        from luna.db.models import RunStatus

        run.status = RunStatus.cancelled
        run.ended_at = datetime.now()
    await session.flush()
    await write_event(
        session,
        actor=body.actor,
        action="proposal.cancel",
        run_id=proposal.run_id,
        result_ref=str(proposal.id),
    )
    await session.commit()
    await session.refresh(proposal)
    return proposal


@router.post("/{proposal_id}/edit", response_model=ProposalOut)
async def edit_proposal(
    proposal_id: uuid.UUID, body: EditBody, session: AsyncSession = Depends(get_db)
) -> Proposal:
    """Only a still-`pending` proposal can be edited. `diff_patch` is merged
    (shallow) into the existing `diff_json`; the `idempotency_key` is always
    recomputed afterward since it's derived from `diff_json`/`kind`/
    `target_jira_key` -- an edited proposal is, by definition, a different
    proposed change and must get a different key."""
    proposal = await _get_proposal_or_404(session, proposal_id)
    _require_status(proposal, ProposalStatus.pending)

    new_diff = {**proposal.diff_json, **body.diff_patch}
    new_key = body.target_jira_key if body.target_jira_key is not None else proposal.target_jira_key

    proposal.diff_json = new_diff
    proposal.target_jira_key = new_key
    proposal.idempotency_key = compute_idempotency_key(
        diff_json=new_diff, kind=proposal.kind, target_jira_key=new_key
    )
    await session.flush()
    await write_event(
        session,
        actor=body.actor,
        action="proposal.edit",
        run_id=proposal.run_id,
        tool_call_json={"diff_patch": body.diff_patch},
        result_ref=str(proposal.id),
    )
    await session.commit()
    await session.refresh(proposal)
    return proposal
