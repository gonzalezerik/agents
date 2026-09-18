"""Tests for luna/adapters/slack_adapter.py.

Bolt's `body`/`view` payloads are already plain dicts (unlike Discord's SDK
objects), so these tests hand-build them directly per Slack's documented
`block_actions`/`view_submission`/slash-command payload shapes -- no live
Socket Mode connection is used, per slack_adapter.py's own "Testing"
docstring section.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from luna.adapters import slack_adapter as sa
from luna.adapters._api_client import LunaAPIError


def make_ack() -> AsyncMock:
    return AsyncMock()


# --------------------------------------------------------------------------
# build_slack_ingest_event
# --------------------------------------------------------------------------


def test_build_slack_ingest_event_slash_command_shape() -> None:
    event = sa.build_slack_ingest_event(
        event_type="slash_command",
        team_id="T1",
        user_id="U1",
        display_name="erik",
        channel_id="C1",
        command_name="budget",
        command_options={"text": ""},
    )
    assert event == {
        "type": "slash_command",
        "team_id": "T1",
        "channel_id": "C1",
        "user": {"platform_user_id": "U1", "display_name": "erik"},
        "command": {"name": "budget", "options": {"text": ""}},
    }
    assert "modal" not in event


# --------------------------------------------------------------------------
# /status modal: view building + submission parsing
# --------------------------------------------------------------------------


def test_build_status_modal_view_has_issue_text_update_text_and_checkbox() -> None:
    view = sa.build_status_modal_view()
    assert view["callback_id"] == sa.STATUS_MODAL_CALLBACK_ID
    block_ids = [b["block_id"] for b in view["blocks"]]
    assert block_ids == ["issue_key_block", "update_text_block", "is_blocker_block"]
    assert view["blocks"][2]["element"]["type"] == "checkboxes"


def test_parse_status_modal_submission_blocker_checked() -> None:
    view = {
        "state": {
            "values": {
                "issue_key_block": {"issue_key": {"value": "C3-9"}},
                "update_text_block": {"update_text": {"value": "did the thing"}},
                "is_blocker_block": {
                    "is_blocker": {"selected_options": [{"value": "blocked"}]}
                },
            }
        }
    }
    fields = sa.parse_status_modal_submission(view)
    assert fields == {"issue_key": "C3-9", "update_text": "did the thing", "is_blocker": True}


def test_parse_status_modal_submission_blank_issue_and_unchecked_box() -> None:
    view = {
        "state": {
            "values": {
                "issue_key_block": {"issue_key": {"value": None}},
                "update_text_block": {"update_text": {"value": "update"}},
                "is_blocker_block": {"is_blocker": {"selected_options": []}},
            }
        }
    }
    fields = sa.parse_status_modal_submission(view)
    assert fields["issue_key"] is None
    assert fields["is_blocker"] is False


async def test_handle_status_command_opens_modal() -> None:
    ack = make_ack()
    client = AsyncMock()
    body = {"trigger_id": "trig1"}

    await sa.handle_status_command(ack, body, client)

    ack.assert_awaited_once()
    client.views_open.assert_awaited_once()
    assert client.views_open.await_args.kwargs["trigger_id"] == "trig1"
    assert client.views_open.await_args.kwargs["view"]["callback_id"] == sa.STATUS_MODAL_CALLBACK_ID


async def test_handle_status_modal_submission_posts_ingest_event() -> None:
    api_client = AsyncMock()
    api_client.ingest_slack.return_value = {"run_id": "r1", "capability": "status_intake"}
    body = {
        "team": {"id": "T1"},
        "user": {"id": "U1", "username": "erik"},
        "view": {
            "state": {
                "values": {
                    "issue_key_block": {"issue_key": {"value": "C3-9"}},
                    "update_text_block": {"update_text": {"value": "done"}},
                    "is_blocker_block": {"is_blocker": {"selected_options": []}},
                }
            }
        },
    }
    ack = make_ack()

    result = await sa.handle_status_modal_submission(ack, body, api_client)

    ack.assert_awaited_once()
    assert result["capability"] == "status_intake"
    sent_event = api_client.ingest_slack.await_args.args[0]
    assert sent_event["type"] == "modal_submit"
    assert sent_event["modal"]["fields"]["issue_key"] == "C3-9"


# --------------------------------------------------------------------------
# Simple slash commands
# --------------------------------------------------------------------------


async def test_handle_slash_command_status_opens_modal_without_ingest() -> None:
    ack = make_ack()
    client = AsyncMock()
    api_client = AsyncMock()
    body = {"trigger_id": "trig1", "team_id": "T1", "channel_id": "C1", "user_id": "U1"}

    result = await sa.handle_slash_command(ack, body, client, api_client, command_name="status")

    assert result is None
    client.views_open.assert_awaited_once()
    api_client.ingest_slack.assert_not_awaited()


async def test_handle_slash_command_record_tells_user_to_use_discord() -> None:
    ack = make_ack()
    client = AsyncMock()
    api_client = AsyncMock()
    body = {"team_id": "T1", "channel_id": "C1", "user_id": "U1"}

    result = await sa.handle_slash_command(ack, body, client, api_client, command_name="record")

    assert result is None
    api_client.ingest_slack.assert_not_awaited()
    client.chat_postEphemeral.assert_awaited_once()
    assert "Discord" in client.chat_postEphemeral.await_args.kwargs["text"]


async def test_handle_slash_command_ask_ingests_and_acks() -> None:
    ack = make_ack()
    client = AsyncMock()
    api_client = AsyncMock()
    api_client.ingest_slack.return_value = {"run_id": "r", "capability": "rag_qna"}
    body = {"team_id": "T1", "channel_id": "C1", "user_id": "U1", "user_name": "erik", "text": "who owns power?"}

    result = await sa.handle_slash_command(ack, body, client, api_client, command_name="ask")

    assert result["capability"] == "rag_qna"
    sent_event = api_client.ingest_slack.await_args.args[0]
    assert sent_event["command"] == {"name": "ask", "options": {"text": "who owns power?"}}
    client.chat_postEphemeral.assert_awaited_once()


async def test_handle_slash_command_ingest_failure_notifies_and_reraises() -> None:
    ack = make_ack()
    client = AsyncMock()
    api_client = AsyncMock()
    api_client.ingest_slack.side_effect = LunaAPIError("down")
    body = {"team_id": "T1", "channel_id": "C1", "user_id": "U1"}

    with pytest.raises(LunaAPIError):
        await sa.handle_slash_command(ack, body, client, api_client, command_name="blockers")

    assert "couldn't reach" in client.chat_postEphemeral.await_args.kwargs["text"]


# --------------------------------------------------------------------------
# Proposal blocks + Confirm/Edit/Cancel actions
# --------------------------------------------------------------------------


def test_build_proposal_blocks_has_three_buttons_with_proposal_id_value() -> None:
    proposal = {
        "id": "p1",
        "kind": "status_update",
        "target_jira_key": "C3-9",
        "diff_json": {"status": {"before": "To Do", "after": "Done"}},
        "confidence": 0.9,
    }
    blocks = sa.build_proposal_blocks(proposal)
    action_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [el["action_id"] for el in action_block["elements"]]
    assert action_ids == ["proposal_confirm", "proposal_edit", "proposal_cancel"]
    assert all(el["value"] == "p1" for el in action_block["elements"])


async def test_handle_proposal_action_confirm_calls_api_and_responds(monkeypatch: pytest.MonkeyPatch) -> None:
    ack = make_ack()
    client = AsyncMock()
    api_client = AsyncMock()
    posted = []

    async def fake_respond(respond_url, text):  # noqa: ANN001
        posted.append((respond_url, text))

    monkeypatch.setattr(sa, "_respond", fake_respond)

    body = {"actions": [{"value": "p1"}], "response_url": "https://hooks.slack.test/x"}
    await sa.handle_proposal_action(ack, body, client, api_client, action_id="proposal_confirm")

    api_client.confirm_proposal.assert_awaited_once_with("p1")
    assert posted == [("https://hooks.slack.test/x", "Confirmed.")]


async def test_handle_proposal_action_edit_opens_modal_with_trigger_id() -> None:
    ack = make_ack()
    client = AsyncMock()
    api_client = AsyncMock()
    body = {"actions": [{"value": "p1"}], "trigger_id": "trig1", "response_url": "https://x"}

    await sa.handle_proposal_action(ack, body, client, api_client, action_id="proposal_edit")

    client.views_open.assert_awaited_once()
    view = client.views_open.await_args.kwargs["view"]
    assert view["private_metadata"] == "p1"
    assert view["callback_id"] == f"{sa.PROPOSAL_EDIT_CALLBACK_PREFIX}p1"
    api_client.confirm_proposal.assert_not_awaited()


async def test_handle_proposal_action_failure_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    ack = make_ack()
    client = AsyncMock()
    api_client = AsyncMock()
    api_client.cancel_proposal.side_effect = LunaAPIError("nope")
    posted = []

    async def fake_respond(respond_url, text):  # noqa: ANN001
        posted.append(text)

    monkeypatch.setattr(sa, "_respond", fake_respond)
    body = {"actions": [{"value": "p1"}], "response_url": "https://x"}

    await sa.handle_proposal_action(ack, body, client, api_client, action_id="proposal_cancel")

    assert posted == ["That didn't go through -- try again."]


async def test_handle_proposal_edit_submission_sends_raw_text() -> None:
    ack = make_ack()
    api_client = AsyncMock()
    body = {
        "view": {
            "private_metadata": "p1",
            "state": {"values": {"edit_block": {"edited_fields": {"value": "status: In Review"}}}},
        }
    }

    await sa.handle_proposal_edit_submission(ack, body, api_client)

    api_client.edit_proposal.assert_awaited_once_with("p1", {"raw_text": "status: In Review"})


def test_proposal_edit_callback_pattern_matches_prefixed_ids() -> None:
    assert sa.PROPOSAL_EDIT_CALLBACK_PATTERN.match("proposal_edit_modal:p1")
    assert not sa.PROPOSAL_EDIT_CALLBACK_PATTERN.match("status_modal")
