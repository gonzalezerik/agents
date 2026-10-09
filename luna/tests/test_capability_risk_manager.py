"""Tests for capability #9 `risk_manager`: the pure `_risk_math` layer (no
DB), the read-only review through the real `control_loop.run()`, and the
notes -> proposal -> confirmed apply -> verify path. Jira, the Decision
Engine and Generation are faked via the module's factory seams."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.capabilities import _risk_math as rm
from luna.capabilities import risk_manager
from luna.capabilities._session import run_with_session
from luna.control_loop import RunStatus
from luna.db.models import JiraChange, Proposal, ProposalStatus
from luna.decision.schemas import Answer, ChoiceAnswer, NoulAnswer, ScoreAnswer

FMAP = risk_manager.DEFAULT_CUSTOM_FIELD_MAP
TODAY = date(2026, 11, 20)
VERSIONS = [
    {
        "id": "1",
        "name": "Midpoint-Showcase-2026-12",
        "releaseDate": "2026-12-07",
        "released": False,
    },
    {"id": "2", "name": "Final-Judging-2027-04", "releaseDate": "2027-04-12", "released": False},
    {"id": "3", "name": "PDR", "releaseDate": "2026-10-01", "released": True},
]


def _issue(
    key: str,
    *,
    lik: float | None,
    imp: float | None,
    score: float | None = None,
    comp: str = "Power",
    assignee: str | None = "Parker",
    updated: str = "2026-11-18T10:00:00.000+0000",
    versions: tuple[str, ...] = ("Midpoint-Showcase-2026-12",),
    links: int = 1,
) -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": f"risk {key}",
            "status": {"name": "To Do"},
            "components": [{"name": comp}],
            "assignee": {"displayName": assignee} if assignee else None,
            "updated": updated,
            "fixVersions": [{"name": v} for v in versions],
            "issuelinks": [{"type": {"name": "relates"}}] * links,
            FMAP["risk_likelihood"]: lik,
            FMAP["risk_impact"]: imp,
            FMAP["risk_score"]: score
            if score is not None
            else (lik * imp if lik and imp else None),
        },
    }


def _items(*issues: dict[str, Any]) -> list[rm.RiskItem]:
    return [rm.parse_risk_issue(i, FMAP) for i in issues]


# -- pure math -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "band"),
    [(1, "LOW"), (4, "LOW"), (5, "MEDIUM"), (12, "MEDIUM"), (15, "HIGH"), (25, "HIGH")],
)
def test_level_bands(score: int, band: str) -> None:
    assert rm.level(score) == band


def test_score_answer_maps_to_one_based_level() -> None:
    assert rm.level_from_score_answer(0.0) == 1
    assert rm.level_from_score_answer(2.4) == 3
    assert rm.level_from_score_answer(3.6) == 5
    assert rm.level_from_score_answer(9.0) == 5


def test_parse_rejects_out_of_range_levels_as_unscored() -> None:
    (r,) = _items(_issue("C3-1", lik=7.0, imp=3.0))
    assert r.likelihood is None and not r.scored


def test_matrix_rendering_labels_band_in_text() -> None:
    risks = _items(
        _issue("C3-1", lik=5.0, imp=4.0),
        _issue("C3-2", lik=5.0, imp=4.0),
        _issue("C3-3", lik=1.0, imp=1.0),
    )
    grid = rm.render_matrix(risks)
    assert "H2" in grid.splitlines()[1]  # likelihood-5 row, two HIGH risks
    assert "L1" in grid.splitlines()[5]


def test_review_findings() -> None:
    risks = _items(
        _issue("C3-1", lik=None, imp=3.0),  # unscored
        _issue("C3-2", lik=3.0, imp=3.0, score=6.0),  # score field out of sync
        _issue("C3-3", lik=2.0, imp=2.0, assignee=None, updated="2026-10-01T00:00:00.000+0000"),
        _issue("C3-4", lik=4.0, imp=5.0, links=0),  # HIGH, unmitigated, 17 days to midpoint
    )
    found = {
        (f.key, f.kind)
        for f in rm.review(
            risks, today=TODAY, milestone_dates={"Midpoint-Showcase-2026-12": date(2026, 12, 7)}
        )
    }
    assert found == {
        ("C3-1", "unscored"),
        ("C3-2", "score_out_of_sync"),
        ("C3-3", "no_owner"),
        ("C3-3", "stale"),
        ("C3-4", "high_without_mitigation"),
        ("C3-4", "high_near_milestone"),
    }


def test_milestone_outlook_independent_probability_and_drivers() -> None:
    risks = _items(
        _issue("C3-1", lik=4.0, imp=5.0),  # p=0.6, major
        _issue("C3-2", lik=3.0, imp=4.0),  # p=0.4, major
        _issue("C3-3", lik=5.0, imp=2.0),  # not major: excluded from p_any
    )
    (mid,) = rm.milestone_outlook(
        risks, {"Midpoint-Showcase-2026-12": date(2026, 12, 7)}, today=TODAY
    )
    assert mid["open_risks"] == 3 and mid["major_risks"] == 2
    assert mid["p_any_major"] == pytest.approx(1 - 0.4 * 0.6)
    assert mid["drivers"][0]["key"] == "C3-1"
    assert mid["drivers"][0]["p_any_if_retired"] == pytest.approx(0.4)


def test_subteam_exposure() -> None:
    risks = _items(
        _issue("C3-1", lik=3.0, imp=5.0, comp="Power"),
        _issue("C3-2", lik=1.0, imp=2.0, comp="Chassis"),
    )
    assert rm.subteam_exposure(risks) == pytest.approx({"Power": 2.0, "Chassis": 0.1})


# -- review mode through the control loop ------------------------------------------


async def test_review_run_produces_report(db_session: AsyncSession) -> None:
    ctx = await run_with_session(
        db_session,
        capability=risk_manager.CAPABILITY,
        trigger_source="test",
        initial_data={
            "issues": [_issue("C3-7", lik=4.0, imp=5.0, links=0), _issue("C3-8", lik=2.0, imp=2.0)],
            "versions": VERSIONS,
            "today": TODAY.isoformat(),
        },
    )
    assert ctx.status == RunStatus.completed
    assert [m["milestone"] for m in ctx.data["milestones"]] == [
        "Midpoint-Showcase-2026-12",
        "Final-Judging-2027-04",
    ]  # released PDR excluded
    md = ctx.data["summary_markdown"]
    assert "1 HIGH, 0 MEDIUM, 1 LOW" in md
    assert "C3-7 HIGH 20" in md
    assert "Midpoint-Showcase-2026-12 in 17 days: 60%" in md
    assert any(f["kind"] == "high_without_mitigation" for f in ctx.data["findings"])


# -- propose mode + apply ------------------------------------------------------------------


class RiskProvider:
    """Answers by question id; candidate text decides is_risk/duplicate."""

    provider_name = "fake"
    model_id = "fake-risk-1"

    async def decide(self, state: Any, questions: dict[str, Any]) -> dict[str, Answer]:
        text = str(state)
        out: dict[str, Answer] = {}
        for qid in questions:
            if qid == "injection_gate":
                out[qid] = NoulAnswer(noul=0.0)
            elif qid == "is_risk":
                out[qid] = NoulAnswer(noul=0.1 if "order the" in text else 0.9)
            elif qid == "component":
                out[qid] = ChoiceAnswer(
                    choice="Power", probabilities={"Power": 1.0}, confidence=1.0
                )
            elif qid in ("likelihood", "impact"):
                out[qid] = ScoreAnswer(
                    score=3.0, legend={}, probabilities={"3": 1.0}, confidence=0.8
                )
            elif qid == "duplicate_of":
                choice = "C3-8" if "battery" in text else risk_manager.NO_DUPLICATE
                out[qid] = ChoiceAnswer(choice=choice, probabilities={choice: 1.0}, confidence=0.9)
        return out


class ListGeneration:
    async def generate(self, *, instructions: str, untrusted: Any = None, **kwargs: Any) -> str:
        return (
            "1. Given we still need to order the motors, there is a possibility that this is a task\n"
            "2. Given the battery pack runs hot in regolith tests, there is a possibility that it shuts down\n"
            "3. Given only one Orin board, there is a possibility that a failure stops all CV work\n"
        )

    async def aclose(self) -> None:
        pass


class FakeJiraWrites:
    def __init__(self, *, land: bool = True) -> None:
        self.land = land
        self.fields: dict[str, dict[str, Any]] = {}
        self.comments: list[tuple[str, str]] = []

    async def create_issue(
        self, *, fields: dict[str, Any], idempotency_key: str, session: Any = None
    ) -> dict[str, Any]:
        self.fields["C3-99"] = dict(fields)
        return {"id": "99", "key": "C3-99"}

    async def update_fields(
        self, key: str, fields: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        self.fields.setdefault(key, {}).update(fields)
        return {"status": 204, "key": key}

    async def add_comment(self, key: str, body: str, **kwargs: Any) -> dict[str, Any]:
        self.comments.append((key, body))
        return {"id": "1"}

    async def get_issue(self, key: str, fields: list[str] | None = None) -> dict[str, Any]:
        got = dict(self.fields.get(key, {}))
        if not self.land:
            got[FMAP["risk_likelihood"]] = None
        return {"key": key, "fields": got}


async def _propose(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, notes: str = "notes from Tuesday"
):
    monkeypatch.setattr(risk_manager, "_provider_factory", RiskProvider)
    monkeypatch.setattr(risk_manager, "_generation_factory", ListGeneration)
    return await run_with_session(
        db_session,
        capability=risk_manager.CAPABILITY,
        trigger_source="test",
        initial_data={
            "command": {"name": "risks", "options": {"notes": notes}},
            "issues": [_issue("C3-8", lik=2.0, imp=3.0)],
            "versions": VERSIONS,
        },
    )


async def test_notes_become_new_and_update_proposals(db_session: AsyncSession, monkeypatch) -> None:
    ctx = await _propose(db_session, monkeypatch)
    assert ctx.status == RunStatus.completed
    rows = (
        (await db_session.execute(select(Proposal).where(Proposal.run_id == ctx.run_id)))
        .scalars()
        .all()
    )
    by_kind = {p.kind: p for p in rows}
    assert set(by_kind) == {"risk_new", "risk_update"}  # the "order the motors" task was dropped

    new = by_kind["risk_new"].diff_json
    assert new["likelihood"] == 4 and new["impact"] == 4  # Score index 3.0 -> level 4
    assert new["level"] == "HIGH" and new["component"] == "Power"
    assert "Orin" in new["statement"]

    upd = by_kind["risk_update"]
    assert upd.target_jira_key == "C3-8"
    assert upd.diff_json["likelihood"] == {"before": 2, "after": 4}
    assert all(p.status == ProposalStatus.pending for p in rows)


async def test_rerun_on_same_notes_reuses_proposals(db_session: AsyncSession, monkeypatch) -> None:
    first = await _propose(db_session, monkeypatch)
    second = await _propose(db_session, monkeypatch)
    assert sorted(first.data["proposal_ids"]) == sorted(second.data["proposal_ids"])


async def test_apply_new_risk_creates_issue_and_verifies(
    db_session: AsyncSession, monkeypatch
) -> None:
    ctx = await _propose(db_session, monkeypatch)
    proposal = (
        await db_session.execute(
            select(Proposal).where(Proposal.run_id == ctx.run_id, Proposal.kind == "risk_new")
        )
    ).scalar_one()
    jira = FakeJiraWrites()
    change = await risk_manager.apply_risk_proposal(
        db_session, proposal, actor="discord:1", jira=jira
    )  # type: ignore[arg-type]

    created = jira.fields["C3-99"]
    assert created["issuetype"] == {"name": "Risk"}
    assert created[FMAP["risk_score"]] == 16
    assert change.verify_ok and proposal.status == ProposalStatus.verified
    assert proposal.target_jira_key == "C3-99"


async def test_apply_update_comments_and_fails_verify_when_fields_dont_land(
    db_session: AsyncSession, monkeypatch
) -> None:
    ctx = await _propose(db_session, monkeypatch)
    proposal = (
        await db_session.execute(
            select(Proposal).where(Proposal.run_id == ctx.run_id, Proposal.kind == "risk_update")
        )
    ).scalar_one()
    jira = FakeJiraWrites(land=False)
    await risk_manager.apply_risk_proposal(db_session, proposal, actor="discord:1", jira=jira)  # type: ignore[arg-type]

    assert jira.comments and jira.comments[0][0] == "C3-8"
    assert proposal.status == ProposalStatus.failed
    change = (
        await db_session.execute(select(JiraChange).where(JiraChange.proposal_id == proposal.id))
    ).scalar_one()
    assert change.before_json == {"likelihood": 2, "impact": 3} and change.verify_ok is False
