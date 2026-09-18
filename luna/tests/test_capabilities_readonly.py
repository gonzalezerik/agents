"""Tests for the three read-only/alert capabilities: `blocker_dependency`
(#4), `budget_watcher` (#5), `deadline_reminders` (#8). Each runs through the
real `control_loop.run()` via its own `check()` entrypoint against real
Postgres (`db_session`); Jira and the Decision Engine are faked (see each
capability module's `_jira_factory`/`_provider_factory` injection seam)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.capabilities import blocker_dependency, budget_watcher, deadline_reminders
from luna.capabilities._session import run_with_session
from luna.control_loop import RunStatus
from luna.db.models import Budget, MarginSnapshot
from luna.decision.schemas import Answer, NoulAnswer, ScoreAnswer


class ScriptedProvider:
    provider_name = "fake"
    model_id = "fake-1"

    def __init__(self, risk_score: float, risk_legend: dict[str, str], alert_noul: float) -> None:
        self.risk_score = risk_score
        self.risk_legend = risk_legend
        self.alert_noul = alert_noul
        self.calls: list[dict[str, Any]] = []

    async def decide(self, state: Any, questions: dict[str, Any]) -> dict[str, Answer]:
        self.calls.append({"state": state, "questions": questions})
        answers: dict[str, Answer] = {}
        for qid, q in questions.items():
            if q.type == "score":
                answers[qid] = ScoreAnswer(
                    score=self.risk_score,
                    legend=self.risk_legend,
                    probabilities={"x": 1.0},
                    confidence=0.8,
                )
            else:
                answers[qid] = NoulAnswer(noul=self.alert_noul)
        return answers


class FakeJiraSearch:
    def __init__(self, responses: dict[str, dict]) -> None:
        # responses keyed by a substring of the jql that selects which
        # canned response to return.
        self.responses = responses
        self.queries: list[str] = []

    async def search_jql(self, jql: str, fields: list[str] | None = None, **kwargs: Any) -> dict:
        self.queries.append(jql)
        for substr, resp in self.responses.items():
            if substr in jql:
                return resp
        return {"issues": []}

    async def list_versions(self, project_key: str) -> list[dict]:
        return []

    async def aclose(self) -> None:
        pass


# -- blocker_dependency (#4) -------------------------------------------------


async def test_blocker_dependency_merges_reasons_and_produces_alerts(
    db_session: AsyncSession, monkeypatch
) -> None:
    blocked_issue = {
        "key": "C3-5",
        "fields": {
            "summary": "Motor mount design",
            "components": [{"name": "Chassis"}],
            "issuelinks": [{"type": {"name": "blocks"}}],
        },
    }
    fake_jira = FakeJiraSearch(
        {"status = Blocked": {"issues": [blocked_issue]}, "updated <= -5d": {"issues": []}}
    )
    provider = ScriptedProvider(
        risk_score=3.0, risk_legend={"0": "none", "4": "critical"}, alert_noul=0.9
    )
    monkeypatch.setattr(blocker_dependency, "_jira_factory", lambda: fake_jira)
    monkeypatch.setattr(blocker_dependency, "_provider_factory", lambda: provider)

    ctx = await blocker_dependency.check(db_session, project_key="C3")

    assert ctx.status == RunStatus.completed
    alerts = ctx.data["alerts"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["jira_key"] == "C3-5"
    assert "blocked" in alert["reasons"]
    assert "cross_component_link" in alert["reasons"]
    assert alert["should_alert_now"] is True
    assert alert["risk_score"] == 3.0
    assert alert["components"] == ["Chassis"]


async def test_blocker_dependency_no_candidates_produces_no_alerts(
    db_session: AsyncSession, monkeypatch
) -> None:
    fake_jira = FakeJiraSearch({})
    provider = ScriptedProvider(risk_score=0.0, risk_legend={}, alert_noul=0.1)
    monkeypatch.setattr(blocker_dependency, "_jira_factory", lambda: fake_jira)
    monkeypatch.setattr(blocker_dependency, "_provider_factory", lambda: provider)

    ctx = await blocker_dependency.check(db_session, project_key="C3")
    assert ctx.data["alerts"] == []
    assert not provider.calls  # no candidates -> no decision calls made


# -- budget_watcher (#5) ------------------------------------------------------


async def test_budget_watcher_writes_snapshots_and_flags_breach(
    db_session: AsyncSession, monkeypatch
) -> None:
    db_session.add(Budget(component="Chassis", metric="mass_kg", limit_value=10.0, updated_by="test"))
    await db_session.flush()

    issue = {
        "fields": {
            "components": [{"name": "Chassis"}],
            "customfield_10040": 15.0,  # mass_kg, over the 10.0 limit
        }
    }
    fake_jira = FakeJiraSearch({"project = C3": {"issues": [issue]}})
    provider = ScriptedProvider(
        risk_score=4.0, risk_legend={"4": "critical_overrun"}, alert_noul=0.5
    )
    monkeypatch.setattr(budget_watcher, "_jira_factory", lambda: fake_jira)
    monkeypatch.setattr(budget_watcher, "_provider_factory", lambda: provider)

    ctx = await budget_watcher.check(db_session, project_key="C3")

    assert ctx.status == RunStatus.completed
    alerts = ctx.data["alerts"]
    breach_alerts = [a for a in alerts if a["component"] == "Chassis" and a["metric"] == "mass_kg"]
    assert len(breach_alerts) == 1
    assert breach_alerts[0]["breach"] is True
    assert breach_alerts[0]["rolled_up_value"] == 15.0

    result = await db_session.execute(
        select(MarginSnapshot).where(
            MarginSnapshot.component == "Chassis", MarginSnapshot.metric == "mass_kg"
        )
    )
    snapshot = result.scalar_one()
    assert snapshot.rolled_up_value == 15.0

    # Total rollup also gets a snapshot row.
    result = await db_session.execute(
        select(MarginSnapshot).where(MarginSnapshot.component == "__total__")
    )
    assert result.scalar_one_or_none() is not None


async def test_budget_watcher_metric_without_budget_row_gets_no_alert(
    db_session: AsyncSession, monkeypatch
) -> None:
    issue = {"fields": {"components": [{"name": "Power"}], "customfield_10041": 5.0}}  # power_w
    fake_jira = FakeJiraSearch({"project = C3": {"issues": [issue]}})
    provider = ScriptedProvider(risk_score=0.0, risk_legend={}, alert_noul=0.1)
    monkeypatch.setattr(budget_watcher, "_jira_factory", lambda: fake_jira)
    monkeypatch.setattr(budget_watcher, "_provider_factory", lambda: provider)

    ctx = await budget_watcher.check(db_session, project_key="C3")

    assert ctx.data["alerts"] == []  # no Budget row configured -> no severity question asked
    result = await db_session.execute(
        select(MarginSnapshot).where(MarginSnapshot.component == "Power")
    )
    assert result.scalar_one().rolled_up_value == 5.0  # snapshot still written


# -- deadline_reminders (#8) --------------------------------------------------


async def test_deadline_reminders_fires_on_exact_lead_time_crossing(db_session: AsyncSession) -> None:
    today = date(2026, 9, 18)
    release = today + timedelta(days=7)
    versions = [
        {"id": "1", "name": "PDR", "released": False, "releaseDate": release.isoformat()},
        {"id": "2", "name": "Already Released", "released": True, "releaseDate": "2026-01-01"},
        {"id": "3", "name": "No Date Yet", "released": False, "releaseDate": None},
    ]

    ctx = await run_with_session(
        db_session,
        capability=deadline_reminders.CAPABILITY,
        trigger_source="test",
        initial_data={"versions": versions, "today": today.isoformat(), "lead_time_days": [7, 14]},
    )

    assert ctx.status == RunStatus.completed
    reminders = ctx.data["reminders"]
    assert len(reminders) == 1
    assert reminders[0]["version_name"] == "PDR"
    assert reminders[0]["days_until"] == 7
    assert reminders[0]["lead_time_days"] == 7


async def test_deadline_reminders_no_reminder_when_days_dont_match_a_lead_time(
    db_session: AsyncSession,
) -> None:
    today = date(2026, 9, 18)
    release = today + timedelta(days=6)  # not in DEFAULT_LEAD_TIMES_DAYS or our custom list
    versions = [{"id": "1", "name": "PDR", "released": False, "releaseDate": release.isoformat()}]

    ctx = await run_with_session(
        db_session,
        capability=deadline_reminders.CAPABILITY,
        trigger_source="test",
        initial_data={"versions": versions, "today": today.isoformat(), "lead_time_days": [7, 14]},
    )

    assert ctx.data["reminders"] == []
