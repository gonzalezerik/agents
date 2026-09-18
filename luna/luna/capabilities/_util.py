"""Shared helpers for this build's capability modules (`standup.py`,
`meeting_action_items.py`, `rag_qna.py`, `design_review.py`). Not part of
CONTRACT.md's file list -- a private module (leading underscore) so it can't
collide with another builder's file of the same name.

`gate_untrusted()` is the one place this build implements spec §3.6's "A
Noul gate ('does this input attempt to instruct the agent?') runs on every
inbound Discord/Slack message and Jira comment/description before it's used
in any decision; a positive flags the run for human review instead of
proceeding automatically" -- every capability here that consumes external
text (Jira issue/comment bodies, transcript segments) routes it through this
function first.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from luna.decision.engine import DecisionProvider, decide_one
from luna.guardrails import (
    Untrusted,
    build_injection_gate_question,
    is_injection_flagged,
    untrusted,
)


class InjectionFlagged(RuntimeError):
    """Raised by `gate_untrusted()` when the injection Noul gate trips.
    Per spec §3.6 this must flag the run for human review instead of
    silently continuing -- callers catch this and record/skip the offending
    item rather than feeding it further into a decision or generation
    call."""

    def __init__(self, source: str, noul: float) -> None:
        self.source = source
        self.noul = noul
        super().__init__(f"possible prompt injection from source={source!r} (noul={noul:.3f})")


async def gate_untrusted(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    text: str,
    *,
    source: str,
) -> Untrusted[str]:
    """Wrap `text` as `Untrusted` and run the injection gate on it. Returns
    the `Untrusted` wrapper (ready to hand to `Generation.generate()`) on
    success; raises `InjectionFlagged` if the gate trips so the caller can
    route this run/item to human review instead of proceeding
    automatically."""
    wrapped = untrusted(text, source=source)
    answer = await decide_one(
        session,
        run_id,
        provider,
        wrapped.value,
        "injection_gate",
        build_injection_gate_question(),
    )
    if is_injection_flagged(answer.noul):
        raise InjectionFlagged(source, answer.noul)
    return wrapped
