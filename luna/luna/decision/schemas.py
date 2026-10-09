"""Question/Answer pydantic models for the Decision Engine.

These shapes mirror the real TypeSafe Jev `/v1/systemone` contract so a
`JevProvider` can be a drop-in for `LocalDecisionProvider` behind the same
`DecisionProvider.decide()` interface.

These models are the schema-conformance boundary: nothing produced by any
`DecisionProvider` implementation is allowed to leave `decide()` without
successfully validating against one of these types. That's what makes
`tests/test_jev_conformance.py` item 1 ("zero off-schema decide() outputs")
meaningful -- these classes *are* the schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: str
    criteria: dict[str, str | None] = Field(description="option_key -> description")

    @model_validator(mode="after")
    def _validate_criteria(self) -> ChoiceQuestion:
        if not (1 <= len(self.criteria) <= 255):
            raise ValueError("ChoiceQuestion.criteria must have between 1 and 255 options")
        return self


class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    instructions: str
    criteria: list[str] = Field(description="2-10 ordered level labels")

    @model_validator(mode="after")
    def _validate_criteria(self) -> ScoreQuestion:
        if not (2 <= len(self.criteria) <= 10):
            raise ValueError("ScoreQuestion.criteria must have between 2 and 10 levels")
        return self


class NoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    instructions: str
    criteria: dict[Literal["true", "false"], str] | None = None


Question = ChoiceQuestion | ScoreQuestion | NoulQuestion


class ChoiceAnswer(BaseModel):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate(self) -> ChoiceAnswer:
        total = sum(self.probabilities.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ChoiceAnswer.probabilities must sum to 1.0 +/- 1e-6, got {total}")
        if self.choice not in self.probabilities:
            raise ValueError("ChoiceAnswer.choice must be a key of its own probabilities map")
        return self


class ScoreAnswer(BaseModel):
    type: Literal["score"] = "score"
    score: float
    legend: dict[str, str] = Field(description="level index (str) -> label")
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate(self) -> ScoreAnswer:
        total = sum(self.probabilities.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ScoreAnswer.probabilities must sum to 1.0 +/- 1e-6, got {total}")
        return self


class NoulAnswer(BaseModel):
    type: Literal["noul"] = "noul"
    noul: float = Field(ge=0.0, le=1.0)


Answer = ChoiceAnswer | ScoreAnswer | NoulAnswer


QUESTION_TYPE_TO_ANSWER_TYPE: dict[str, type[BaseModel]] = {
    "choice": ChoiceAnswer,
    "score": ScoreAnswer,
    "noul": NoulAnswer,
}
