"""Hash-chained `audit_event` writer/reader (CONTRACT.md, spec §3.6).

Every run, prompt, tool call, and decision must be logged and tamper-evident.
Each row's `hash_self` is a SHA-256 over its own fields *and* the previous
row's `hash_self` (`hash_prev`), so altering or deleting a historical row
breaks the chain from that point forward -- `verify_chain()` walks the whole
table (or a `run_id` slice, though a per-run slice only proves *that run's*
rows are internally consistent with each other; full tamper-evidence needs
the global walk, see its docstring) and reports the first row where the
stored hash doesn't match a recomputed one.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.db.models import AuditEvent


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def compute_row_hash(
    *,
    run_id: uuid.UUID | None,
    ts: datetime,
    actor: str,
    action: str,
    prompt_ref: str | None,
    tool_call_json: dict | None,
    result_ref: str | None,
    hash_prev: str | None,
) -> str:
    payload = _canonical(
        {
            "run_id": str(run_id) if run_id else None,
            "ts": ts.isoformat(),
            "actor": actor,
            "action": action,
            "prompt_ref": prompt_ref,
            "tool_call_json": tool_call_json,
            "result_ref": result_ref,
            "hash_prev": hash_prev,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _get_last_hash(session: AsyncSession) -> str | None:
    stmt = select(AuditEvent.hash_self).order_by(AuditEvent.id.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def write_event(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    run_id: uuid.UUID | None = None,
    prompt_ref: str | None = None,
    tool_call_json: dict | None = None,
    result_ref: str | None = None,
) -> AuditEvent:
    """Append one row to the chain. Must be called with the same session
    approach every time (never write audit_event rows through any other
    path) so `hash_prev` always reflects true insertion order.

    Concurrency note: this reads the last hash and then inserts within the
    same session/transaction; under concurrent writers from different
    sessions there is a race between "read last hash" and "insert" that
    could interleave two chains built on the same `hash_prev`. Postgres will
    not stop that at the schema level (there's no unique constraint tying
    `id` order to `hash_prev` correctness) -- the safe pattern for
    multi-process callers (api, worker, discord, slack all writing) is to
    serialize audit writes through a single `SELECT ... FOR UPDATE` guard or
    a dedicated writer process/queue. Not implemented here (noted as a v1
    gap in NOTES.md) -- v1 has low write concurrency (guardrail-gated writes
    only) so the exposure window is small, but a future integrator adding
    high-concurrency capabilities should close this before relying on the
    chain for real tamper-evidence guarantees under load.
    """
    hash_prev = await _get_last_hash(session)
    ts = datetime.now()
    hash_self = compute_row_hash(
        run_id=run_id,
        ts=ts,
        actor=actor,
        action=action,
        prompt_ref=prompt_ref,
        tool_call_json=tool_call_json,
        result_ref=result_ref,
        hash_prev=hash_prev,
    )
    row = AuditEvent(
        run_id=run_id,
        ts=ts,
        actor=actor,
        action=action,
        prompt_ref=prompt_ref,
        tool_call_json=tool_call_json,
        result_ref=result_ref,
        hash_prev=hash_prev,
        hash_self=hash_self,
    )
    session.add(row)
    await session.flush()
    return row


@dataclass
class ChainVerificationResult:
    ok: bool
    rows_checked: int
    first_broken_id: int | None = None
    reason: str | None = None


async def verify_chain(
    session: AsyncSession, *, run_id: uuid.UUID | None = None
) -> ChainVerificationResult:
    """Walk `audit_event` in `id` order and recompute each row's hash,
    checking it against the stored `hash_self` and that `hash_prev` matches
    the prior row actually walked.

    If `run_id` is given, only that run's rows are *checked* for internal
    hash correctness, but `hash_prev` continuity is still validated against
    whatever the immediately-preceding row in the row's own `hash_prev`
    chain was recorded as -- we do not require ordering to be consecutive.
    Tampering with a row belonging to a *different* run can still be
    detected by a run_id-scoped check indirectly, because that row's
    hash_prev linkage feeds into subsequent rows regardless of run -- but a
    run-scoped call does not walk those interleaved other-run rows itself, so
    it cannot itself flag a corruption localized entirely within another
    run's rows. Run an unscoped call periodically (or in CI/ops tooling) for
    a full-database guarantee; the run-scoped call is for "did anything
    happen to *this* run's own audit trail" style questions in `GET
    /audit`/`GET /runs/{id}`.
    """
    stmt = select(AuditEvent).order_by(AuditEvent.id.asc())
    result = await session.execute(stmt)
    rows = result.scalars().all()

    prev_hash: str | None = None
    checked = 0
    for row in rows:
        expected = compute_row_hash(
            run_id=row.run_id,
            ts=row.ts,
            actor=row.actor,
            action=row.action,
            prompt_ref=row.prompt_ref,
            tool_call_json=row.tool_call_json,
            result_ref=row.result_ref,
            hash_prev=row.hash_prev,
        )
        if row.hash_prev != prev_hash:
            return ChainVerificationResult(
                ok=False,
                rows_checked=checked,
                first_broken_id=row.id,
                reason=f"hash_prev mismatch at id={row.id}: stored={row.hash_prev!r} expected={prev_hash!r}",
            )
        if row.hash_self != expected:
            return ChainVerificationResult(
                ok=False,
                rows_checked=checked,
                first_broken_id=row.id,
                reason=f"hash_self mismatch at id={row.id}: stored={row.hash_self!r} recomputed={expected!r}",
            )
        prev_hash = row.hash_self
        if run_id is None or row.run_id == run_id:
            checked += 1

    return ChainVerificationResult(ok=True, rows_checked=checked)
