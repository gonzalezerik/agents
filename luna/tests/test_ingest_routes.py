"""Tests for luna/api/routes/ingest.py against a real Postgres instance
(`db_session` fixture, same discipline as tests/test_control_loop.py --
control_loop.run() writes real agent_run/checkpoint rows, not mocked).

Builds a minimal FastAPI app with only `ingest.router` mounted (this route's
own docstring says not to touch `luna/api/main.py`, which is scoped to
another build), and overrides `get_db` to use the shared `db_session`
fixture and `require_service_token` to a fixed test token so auth can be
exercised explicitly in its own tests.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.api import deps
from luna.api.routes import ingest
from luna.audit import AuditEvent
from luna.db.models import AgentRun

TEST_TOKEN = "test-internal-service-token"


def make_app(db_session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.include_router(ingest.router)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[deps.get_db] = _override_get_db
    return app


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture(autouse=True)
def _configure_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from luna.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "internal_service_token", TEST_TOKEN)


@pytest.fixture
async def client(db_session: AsyncSession):
    app = make_app(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


async def test_ingest_discord_requires_bearer_token(client: AsyncClient) -> None:
    resp = await client.post("/ingest/discord", json={})
    assert resp.status_code == 401


async def test_ingest_discord_rejects_wrong_token(client: AsyncClient) -> None:
    resp = await client.post(
        "/ingest/discord", json={}, headers={"Authorization": "Bearer wrong"}
    )
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# Discord: slash_command / modal_submit / voice_recording
# --------------------------------------------------------------------------


async def test_ingest_discord_slash_command_creates_run(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    payload = {
        "type": "slash_command",
        "guild_id": "g1",
        "channel_id": "c1",
        "interaction_id": "i1",
        "user": {"platform_user_id": "u1", "display_name": "Erik"},
        "command": {"name": "budget", "options": {}},
    }
    resp = await client.post("/ingest/discord", json=payload, headers=auth_headers)
    assert resp.status_code == 202
    body = resp.json()
    assert body["capability"] == "budget_watcher"
    assert body["status"] == "completed"

    run = await db_session.get(AgentRun, uuid.UUID(body["run_id"]))
    assert run is not None
    assert run.trigger_source == "discord"
    assert run.actor_user == "discord:u1"
    assert run.checkpoint_json["data"]["command"]["name"] == "budget"


async def test_ingest_discord_modal_submit_maps_status_to_status_intake(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {
        "type": "modal_submit",
        "channel_id": "c1",
        "user": {"platform_user_id": "u1"},
        "command": {"name": "status", "options": {}},
        "modal": {
            "custom_id": "status_modal",
            "fields": {"issue_key": "C3-9", "update_text": "did stuff", "is_blocker": False},
        },
    }
    resp = await client.post("/ingest/discord", json=payload, headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["capability"] == "status_intake"


async def test_ingest_discord_voice_recording_maps_to_meeting_action_items(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {
        "type": "voice_recording",
        "channel_id": "c1",
        "guild_id": "g1",
        "user": {"platform_user_id": "u1"},
        "voice_recording": {
            "garage_key": "voice/g1/c1/abc-u1.pcm",
            "duration_seconds": 12.5,
            "sample_rate_hz": 48000,
            "channels": 2,
        },
    }
    resp = await client.post("/ingest/discord", json=payload, headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["capability"] == "meeting_action_items"


async def test_ingest_discord_unrouted_command_is_400(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {
        "type": "slash_command",
        "channel_id": "c1",
        "user": {"platform_user_id": "u1"},
        "command": {"name": "not_a_real_command", "options": {}},
    }
    resp = await client.post("/ingest/discord", json=payload, headers=auth_headers)
    assert resp.status_code == 400


async def test_ingest_discord_slash_command_without_command_field_is_422(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {"type": "slash_command", "channel_id": "c1", "user": {"platform_user_id": "u1"}}
    resp = await client.post("/ingest/discord", json=payload, headers=auth_headers)
    assert resp.status_code == 422


async def test_ingest_discord_writes_audit_event(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    payload = {
        "type": "slash_command",
        "channel_id": "c1",
        "user": {"platform_user_id": "u1"},
        "command": {"name": "blockers", "options": {}},
    }
    resp = await client.post("/ingest/discord", json=payload, headers=auth_headers)
    run_id = uuid.UUID(resp.json()["run_id"])

    result = await db_session.execute(select(AuditEvent).where(AuditEvent.run_id == run_id))
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].action == "ingest.discord.slash_command"
    assert events[0].actor == "discord:u1"


# --------------------------------------------------------------------------
# Slack
# --------------------------------------------------------------------------


async def test_ingest_slack_slash_command_creates_run(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    payload = {
        "type": "slash_command",
        "team_id": "T1",
        "channel_id": "C1",
        "user": {"platform_user_id": "U1", "display_name": "erik"},
        "command": {"name": "ask", "options": {"text": "who owns power?"}},
    }
    resp = await client.post("/ingest/slack", json=payload, headers=auth_headers)
    assert resp.status_code == 202
    body = resp.json()
    assert body["capability"] == "rag_qna"

    run = await db_session.get(AgentRun, uuid.UUID(body["run_id"]))
    assert run.trigger_source == "slack"
    assert run.actor_user == "slack:U1"


async def test_ingest_slack_modal_submit_requires_modal_field(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {
        "type": "modal_submit",
        "team_id": "T1",
        "user": {"platform_user_id": "U1"},
        "command": {"name": "status", "options": {}},
    }
    resp = await client.post("/ingest/slack", json=payload, headers=auth_headers)
    assert resp.status_code == 422


async def test_ingest_slack_channel_id_is_optional(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {
        "type": "slash_command",
        "team_id": "T1",
        "user": {"platform_user_id": "U1"},
        "command": {"name": "standup", "options": {}},
    }
    resp = await client.post("/ingest/slack", json=payload, headers=auth_headers)
    assert resp.status_code == 202
