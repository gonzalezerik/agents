"""Tests for `luna/adapters/jira.py` -- realistic Jira Cloud REST v3 response
shapes mocked via `respx` (no real Jira site exists, see the adapter's module
docstring). Covers every required method, the ADF comment-body wrapping, the
`add_worklog` exactly-one-of validation, and -- the two things the task brief
calls out explicitly -- idempotency (double-apply is a no-op) and the
`JiraNotConfiguredError` fail-loud path.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from luna.adapters.jira import JiraAdapter, JiraNotConfiguredError
from luna.config import Settings
from luna.db.models import AgentRun, Proposal, ProposalStatus, RunStatus

BASE = "https://testsite.atlassian.net/rest/api/3"


def _settings(**overrides: object) -> Settings:
    base = {
        "jira_site": "testsite",
        "jira_email": "bot@example.com",
        "jira_api_token": "tok",
    }
    base.update(overrides)
    return Settings(**base)


def test_missing_credentials_raises_clearly() -> None:
    with pytest.raises(JiraNotConfiguredError, match="JIRA_SITE"):
        JiraAdapter(Settings(jira_site="", jira_email="", jira_api_token=""))


def test_missing_only_token_raises_naming_it() -> None:
    with pytest.raises(JiraNotConfiguredError, match="JIRA_API_TOKEN"):
        JiraAdapter(Settings(jira_site="testsite", jira_email="bot@example.com", jira_api_token=""))


async def _make_run(session: AsyncSession) -> uuid.UUID:
    run = AgentRun(
        capability="status_intake", trigger_source="test", status=RunStatus.decide, checkpoint_json={}
    )
    session.add(run)
    await session.flush()
    return run.id


@respx.mock
async def test_search_jql_hits_new_search_endpoint_and_parses_response() -> None:
    route = respx.post(f"{BASE}/search/jql").mock(
        return_value=httpx.Response(
            200,
            json={
                "issues": [
                    {"id": "10001", "key": "C3-1", "fields": {"summary": "Wire harness"}},
                ],
                "nextPageToken": None,
                "isLast": True,
            },
        )
    )
    jira = JiraAdapter(_settings())
    try:
        result = await jira.search_jql("project = C3", fields=["summary"])
    finally:
        await jira.aclose()

    assert route.called
    request_body = route.calls[0].request.content
    assert b"project = C3" in request_body
    assert result["issues"][0]["key"] == "C3-1"
    assert result["isLast"] is True


@respx.mock
async def test_get_issue() -> None:
    respx.get(f"{BASE}/issue/C3-1").mock(
        return_value=httpx.Response(
            200, json={"id": "10001", "key": "C3-1", "fields": {"summary": "Wire harness"}}
        )
    )
    jira = JiraAdapter(_settings())
    try:
        issue = await jira.get_issue("C3-1", fields=["summary"])
    finally:
        await jira.aclose()
    assert issue["key"] == "C3-1"
    assert issue["fields"]["summary"] == "Wire harness"


@respx.mock
async def test_list_components_and_versions() -> None:
    respx.get(f"{BASE}/project/C3/components").mock(
        return_value=httpx.Response(200, json=[{"id": "1", "name": "Chassis"}])
    )
    respx.get(f"{BASE}/project/C3/versions").mock(
        return_value=httpx.Response(
            200, json=[{"id": "1", "name": "PDR", "released": False, "releaseDate": None}]
        )
    )
    jira = JiraAdapter(_settings())
    try:
        components = await jira.list_components("C3")
        versions = await jira.list_versions("C3")
    finally:
        await jira.aclose()
    assert components == [{"id": "1", "name": "Chassis"}]
    assert versions[0]["name"] == "PDR"


@respx.mock
async def test_create_issue_real_write() -> None:
    route = respx.post(f"{BASE}/issue").mock(
        return_value=httpx.Response(
            201, json={"id": "10010", "key": "C3-10", "self": f"{BASE}/issue/10010"}
        )
    )
    jira = JiraAdapter(_settings())
    try:
        result = await jira.create_issue(
            fields={"project": {"key": "C3"}, "summary": "New req"}, idempotency_key="k1"
        )
    finally:
        await jira.aclose()
    assert route.called
    assert result["key"] == "C3-10"
    assert "idempotent_noop" not in result


@respx.mock
async def test_transition_issue_204_response_shape() -> None:
    respx.post(f"{BASE}/issue/C3-1/transitions").mock(return_value=httpx.Response(204))
    jira = JiraAdapter(_settings())
    try:
        result = await jira.transition_issue("C3-1", "31", idempotency_key="k2")
    finally:
        await jira.aclose()
    assert result == {"status": 204, "key": "C3-1", "transition_id": "31"}


@respx.mock
async def test_add_comment_wraps_body_in_adf() -> None:
    route = respx.post(f"{BASE}/issue/C3-1/comment").mock(
        return_value=httpx.Response(
            201, json={"id": "9001", "body": {"type": "doc", "version": 1, "content": []}}
        )
    )
    jira = JiraAdapter(_settings())
    try:
        await jira.add_comment("C3-1", "done for today", idempotency_key="k3")
    finally:
        await jira.aclose()
    sent = route.calls[0].request.content
    assert b'"type":"doc"' in sent
    assert b'"version":1' in sent
    assert b"done for today" in sent


@respx.mock
async def test_update_fields_put() -> None:
    route = respx.put(f"{BASE}/issue/C3-1").mock(return_value=httpx.Response(204))
    jira = JiraAdapter(_settings())
    try:
        result = await jira.update_fields("C3-1", {"summary": "renamed"}, idempotency_key="k4")
    finally:
        await jira.aclose()
    assert route.called
    assert result["status"] == 204


async def test_add_worklog_requires_exactly_one_time_field() -> None:
    jira = JiraAdapter(_settings())
    try:
        with pytest.raises(ValueError, match="exactly one"):
            await jira.add_worklog("C3-1", idempotency_key="k5")
        with pytest.raises(ValueError, match="exactly one"):
            await jira.add_worklog(
                "C3-1", idempotency_key="k5", time_spent_seconds=60, time_spent="1m"
            )
    finally:
        await jira.aclose()


@respx.mock
async def test_add_worklog_success() -> None:
    route = respx.post(f"{BASE}/issue/C3-1/worklog").mock(
        return_value=httpx.Response(201, json={"id": "1", "timeSpentSeconds": 3600})
    )
    jira = JiraAdapter(_settings())
    try:
        result = await jira.add_worklog(
            "C3-1", idempotency_key="k6", time_spent_seconds=3600, comment="worked on it"
        )
    finally:
        await jira.aclose()
    assert route.called
    assert result["timeSpentSeconds"] == 3600


# -- idempotency: double-apply is a no-op (checked against Proposal state) --


@respx.mock
async def test_write_no_ops_when_proposal_already_applied(db_session: AsyncSession) -> None:
    run_id = await _make_run(db_session)
    idempotency_key = "already-applied-key"
    proposal = Proposal(
        run_id=run_id,
        kind="status_transition",
        target_jira_key="C3-1",
        diff_json={"transition_id": "31"},
        confidence=0.9,
        status=ProposalStatus.applied,
        created_by_agent="status_intake",
        idempotency_key=idempotency_key,
    )
    db_session.add(proposal)
    await db_session.flush()

    route = respx.post(f"{BASE}/issue/C3-1/transitions").mock(return_value=httpx.Response(204))

    jira = JiraAdapter(_settings())
    try:
        result = await jira.transition_issue(
            "C3-1", "31", idempotency_key=idempotency_key, session=db_session
        )
    finally:
        await jira.aclose()

    assert route.called is False
    assert result["idempotent_noop"] is True
    assert result["idempotency_key"] == idempotency_key
    assert result["proposal_id"] == str(proposal.id)


@respx.mock
async def test_write_proceeds_when_no_matching_proposal(db_session: AsyncSession) -> None:
    route = respx.post(f"{BASE}/issue/C3-2/transitions").mock(return_value=httpx.Response(204))
    jira = JiraAdapter(_settings())
    try:
        result = await jira.transition_issue(
            "C3-2", "31", idempotency_key="brand-new-key", session=db_session
        )
    finally:
        await jira.aclose()
    assert route.called is True
    assert "idempotent_noop" not in result


@respx.mock
async def test_write_proceeds_when_proposal_still_pending(db_session: AsyncSession) -> None:
    """A pending (not yet applied/verified) proposal must NOT be treated as
    already-applied -- otherwise a legitimate first apply would be silently
    skipped."""
    run_id = await _make_run(db_session)
    idempotency_key = "pending-key"
    db_session.add(
        Proposal(
            run_id=run_id,
            kind="status_transition",
            target_jira_key="C3-3",
            diff_json={"transition_id": "31"},
            confidence=0.9,
            status=ProposalStatus.pending,
            created_by_agent="status_intake",
            idempotency_key=idempotency_key,
        )
    )
    await db_session.flush()

    route = respx.post(f"{BASE}/issue/C3-3/transitions").mock(return_value=httpx.Response(204))
    jira = JiraAdapter(_settings())
    try:
        result = await jira.transition_issue(
            "C3-3", "31", idempotency_key=idempotency_key, session=db_session
        )
    finally:
        await jira.aclose()
    assert route.called is True
    assert "idempotent_noop" not in result


@respx.mock
async def test_write_with_no_session_always_proceeds() -> None:
    """`session=None` (the seed script's path -- not part of the
    proposal->confirm->apply lifecycle) always makes the real call; there's
    no Proposal row to check against outside that lifecycle."""
    route = respx.post(f"{BASE}/issue").mock(
        return_value=httpx.Response(201, json={"id": "1", "key": "C3-99", "self": "x"})
    )
    jira = JiraAdapter(_settings())
    try:
        result = await jira.create_issue(fields={"summary": "seeded"}, idempotency_key="seed:epic:x")
    finally:
        await jira.aclose()
    assert route.called is True
    assert result["key"] == "C3-99"
