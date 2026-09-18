"""`DecisionProvider` protocol + `decide_one`/`decide_many` helpers.

CONTRACT.md: "Never let a capability call the local LLM directly for a
decision -- it must go through `DecisionProvider.decide()`." This module is
that one door. Free-form prose goes through `Generation.generate()` instead
(owned elsewhere, not imported here) -- the two are never mixed in one call.

`decide_one`/`decide_many` are the layer capabilities actually call: they
wrap a bare `DecisionProvider.decide()` with the audit/caching behavior
CONTRACT.md requires ("every decide() call writes one decision_call row...
cache on (state_hash, questions_hash, model_id) so a retried capability run
doesn't re-call the model").
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.config import Settings, get_settings
from luna.db.models import DecisionCall
from luna.decision.schemas import Answer, Question


def _canonical_json(value: Any) -> str:
    """Deterministic JSON serialization for hashing (sorted keys, no
    whitespace ambiguity) -- pydantic models are dumped via `.model_dump()`
    first so field order in source doesn't affect the hash."""

    def _default(obj: Any) -> Any:
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        raise TypeError(f"not JSON serializable: {type(obj)!r}")

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_default)


def hash_state(state: str | dict | list) -> str:
    return hashlib.sha256(_canonical_json(state).encode("utf-8")).hexdigest()


def hash_questions(questions: dict[str, Question]) -> str:
    return hashlib.sha256(_canonical_json(questions).encode("utf-8")).hexdigest()


@runtime_checkable
class DecisionProvider(Protocol):
    """CONTRACT.md's `DecisionProvider` interface, verbatim."""

    provider_name: str
    model_id: str

    async def decide(
        self, state: str | dict | list, questions: dict[str, Question]
    ) -> dict[str, Answer]: ...


def get_decision_provider(settings: Settings | None = None) -> DecisionProvider:
    """The provider factory. Always returns `LocalDecisionProvider` unless
    `DECISION_PROVIDER=jev` *and* `settings.allow_jev_provider()` is True --
    presence of `TYPESAFE_API_KEY` alone is never enough (CONTRACT.md).
    """
    settings = settings or get_settings()

    if settings.decision_provider == "jev":
        if not settings.allow_jev_provider():
            raise RuntimeError(
                "DECISION_PROVIDER=jev but cloud decisions are not enabled: "
                "both TYPESAFE_API_KEY must be set and ALLOW_CLOUD_DECISIONS=true. "
                "Falling back is not automatic -- fix config or leave DECISION_PROVIDER=local."
            )
        from luna.decision.jev_provider import JevProvider

        return JevProvider(api_key=settings.typesafe_api_key)

    from luna.decision.local_provider import LocalDecisionProvider

    return LocalDecisionProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )


async def _lookup_cached(
    session: AsyncSession, provider: DecisionProvider, state_hash: str, questions_hash: str
) -> DecisionCall | None:
    stmt = (
        select(DecisionCall)
        .where(
            DecisionCall.state_hash == state_hash,
            DecisionCall.provider == provider.provider_name,
            DecisionCall.model_id == provider.model_id,
        )
        .order_by(DecisionCall.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    # state_hash alone can collide across different question sets issued
    # against the same state (e.g. two capabilities on one Jira event); the
    # index is on state_hash for locality, but the cache key is the full
    # triplet, so re-check questions_hash (kept out of the indexed column
    # set per CONTRACT.md's schema -- it's derivable from questions_json).
    if hashlib.sha256(_canonical_json(row.questions_json).encode()).hexdigest() != questions_hash:
        return None
    return row


async def decide_many(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    state: str | dict | list,
    questions: dict[str, Question],
) -> dict[str, Answer]:
    """The one entrypoint capabilities call. Writes exactly one
    `decision_call` row per invocation, reusing a cached row instead of
    re-calling the model when (state_hash, questions_hash, model_id,
    provider) already matches a prior call."""
    if not questions:
        raise ValueError("decide_many requires at least one question")

    state_hash = hash_state(state)
    questions_hash = hash_questions(questions)

    cached = await _lookup_cached(session, provider, state_hash, questions_hash)
    if cached is not None:
        question_types = {qid: q.type for qid, q in questions.items()}
        return {
            qid: _parse_answer(question_types[qid], raw) for qid, raw in cached.answers_json.items()
        }

    answers = await provider.decide(state, questions)

    row = DecisionCall(
        run_id=run_id,
        provider=provider.provider_name,
        model_id=provider.model_id,
        state_hash=state_hash,
        questions_json={qid: q.model_dump(mode="json") for qid, q in questions.items()},
        answers_json={qid: a.model_dump(mode="json") for qid, a in answers.items()},
        logprobs_json=getattr(provider, "last_logprobs", None),
        confidence=_summary_confidence(answers),
    )
    session.add(row)
    await session.flush()

    return answers


async def decide_one(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    state: str | dict | list,
    question_id: str,
    question: Question,
) -> Answer:
    """Convenience wrapper for the common single-question case."""
    answers = await decide_many(session, run_id, provider, state, {question_id: question})
    return answers[question_id]


def _parse_answer(question_type: str, raw: dict[str, Any]) -> Answer:
    from luna.decision.schemas import QUESTION_TYPE_TO_ANSWER_TYPE

    answer_cls = QUESTION_TYPE_TO_ANSWER_TYPE[question_type]
    return answer_cls.model_validate(raw)  # type: ignore[return-value]


def _summary_confidence(answers: dict[str, Answer]) -> float | None:
    """`decision_call.confidence` is a single column; when a batch answers
    multiple questions we store the mean confidence across the Choice/Score
    answers in the batch (Noul has no confidence field per spec). None if
    the batch is Noul-only."""
    values = [a.confidence for a in answers.values() if hasattr(a, "confidence")]
    if not values:
        return None
    return sum(values) / len(values)
