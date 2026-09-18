"""`JevProvider` -- the exact TypeSafe `/v1/systemone` contract (spec §3.9),
a drop-in for `DecisionProvider` if the team is ever given a real API key.

**Ships disabled.** `luna.decision.engine.get_decision_provider()` refuses to
construct this unless both `TYPESAFE_API_KEY` is set and
`ALLOW_CLOUD_DECISIONS=true` -- see `Settings.allow_jev_provider()`. This
class itself does not re-check that gate (the factory is the single
enforcement point so there's exactly one place to audit), but it does refuse
to be constructed with an empty API key, as a second, cheap line of defense
against accidental direct instantiation.

Jev is cloud-only, closed-weight, early-access/waitlisted (spec §1.1) -- this
provider has **not** been exercised against a real TypeSafe endpoint (no key
was available while building this). It is written strictly from the
published contract in spec §3.9 and is unit-tested against a mocked
response shape only.
"""

from __future__ import annotations

from typing import Any

import httpx

from luna.decision.schemas import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
)

_TYPESAFE_BASE_URL = "https://api.typesafe.ai/v1"


class JevProvider:
    provider_name = "jev"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "jev-latest",
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError(
                "JevProvider requires a non-empty api_key -- it must never be "
                "constructed with a placeholder. Use get_decision_provider() "
                "instead of instantiating this directly."
            )
        self.model_id = model
        self._client = client or httpx.AsyncClient(
            base_url=_TYPESAFE_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def decide(
        self, state: str | dict | list, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        body = {
            "state": state,
            "model": self.model_id,
            "questions": {qid: _question_to_wire(q) for qid, q in questions.items()},
        }
        resp = await self._client.post("/systemone", json=body)
        resp.raise_for_status()
        data = resp.json()

        answers: dict[str, Answer] = {}
        for qid, raw in data["answers"].items():
            question = questions[qid]
            answers[qid] = _wire_to_answer(question, raw)
        return answers


def _question_to_wire(question: Question) -> dict[str, Any]:
    if isinstance(question, ChoiceQuestion):
        return {
            "type": "choice",
            "instructions": question.instructions,
            "criteria": question.criteria,
        }
    if isinstance(question, ScoreQuestion):
        return {
            "type": "score",
            "instructions": question.instructions,
            "criteria": question.criteria,
        }
    if isinstance(question, NoulQuestion):
        wire: dict[str, Any] = {"type": "noul", "instructions": question.instructions}
        if question.criteria:
            wire["criteria"] = question.criteria
        return wire
    raise TypeError(f"unknown question type: {question!r}")


def _wire_to_answer(question: Question, raw: dict[str, Any]) -> Answer:
    if isinstance(question, ChoiceQuestion):
        return ChoiceAnswer.model_validate(raw)
    if isinstance(question, ScoreQuestion):
        return ScoreAnswer.model_validate(raw)
    if isinstance(question, NoulQuestion):
        return NoulAnswer.model_validate(raw)
    raise TypeError(f"unknown question type: {question!r}")
