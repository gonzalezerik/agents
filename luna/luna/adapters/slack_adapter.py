"""SlackAdapter (CONTRACT.md `luna/adapters/slack_adapter.py`, spec §1.5/§3.8).

## Socket Mode really does need no public endpoint (verified)

Checked against `slack_bolt.async_app.AsyncApp` and
`slack_bolt.adapter.socket_mode.async_handler.AsyncSocketModeHandler`'s real
constructor signatures (installed `slack-bolt` 1.30.0): `AsyncApp` only needs
`token=` (the bot token) to run under Socket Mode -- `signing_secret` is for
verifying inbound HTTP request signatures, which only matters for Bolt's HTTP
adapter (Flask/FastAPI-mounted webhook route), never constructed here.
`AsyncSocketModeHandler(app, app_token=...)` opens an *outbound* WebSocket
connection to Slack; nothing in this module listens on a port or needs an
Ingress/route. This confirms spec §1.5's claim and CONTRACT.md's "no public
endpoint" note for real, against the actual library, not just the docs.

## Mirror surface, never authoritative (spec §3.1 pushback #4)

Every write this module makes goes through `LunaAPIClient`
(`luna/adapters/_api_client.py`) to **this same service's own** `luna-api`
-- `POST /ingest/slack` (this build's own route) and `POST
/proposals/{id}/confirm|cancel|edit` (another builder's route, may not
exist yet; failures surface as `LunaAPIError`, handled the same as any
other API failure). Slack never gets its own copy of proposal state; every
button/modal here is a thin read-through/write-through client of the one
`luna-api`, matching `discord_adapter.py`'s design exactly. `/record` is
intentionally **not** wired to voice capture here -- spec §3.3 capability #3
is Discord-voice-only (Pycord sinks); this module's `/record` handler just
tells the user to use Discord.

## Modal fields: mostly the same deviation as Discord, one exception

Unlike Discord's stable `Modal` API (text inputs only, see
`discord_adapter.py`'s docstring), Slack's Block Kit modals natively support
`checkboxes` and `static_select` elements inside an `input` block -- verified
against the `views.open`/Block Kit schema. So the blocker flag here **is** a
native `checkboxes` element (`build_status_modal_view`), not a parsed
yes/no text field. The issue-picker, however, is still a plain
`plain_text_input` for the same reason as Discord: populating a live
`static_select` needs a JQL-candidate-search call that would live in
`capabilities/status_intake.py` + `adapters/jira.py`, neither of which exist
in this worktree.

## Proposal edit modal genuinely opens from the button click

Slack's `block_actions` interactive payload carries a `trigger_id` just like
a slash command does, so `handle_proposal_action` opens
`build_proposal_edit_modal_view` directly via `views.open` on the Edit
button -- no "go do this in Discord instead" workaround needed here (unlike
a first draft of this module, which punted; not needed once the payload was
actually checked). `proposal_id` is threaded through as the edit modal's
`private_metadata` so the view_submission handler doesn't need any other
state.

## Testing

Every `handle_*`/`build_*`/`parse_*` function below takes plain dicts
(Bolt's `body`/`view` payloads are already plain dicts, not SDK objects --
unlike Discord's Interaction objects) or a fake `ack`/`client`, so
`tests/test_adapters_slack.py` calls them directly with hand-built payload
dicts (Bolt itself documents constructing these for unit tests). No live
Socket Mode connection is used or needed. `register_handlers`/`build_app`
(the actual `AsyncApp` wiring) are intentionally left untested -- thin glue,
no branches, not exercisable without a live connection.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from luna.adapters._api_client import LunaAPIClient, LunaAPIError
from luna.config import get_settings

logger = logging.getLogger("luna.adapters.slack")

SLASH_COMMANDS = ("status", "ask", "standup", "record", "blockers", "budget", "risks")
STATUS_MODAL_CALLBACK_ID = "status_modal"
PROPOSAL_EDIT_CALLBACK_PREFIX = "proposal_edit_modal:"
PROPOSAL_EDIT_CALLBACK_PATTERN = re.compile(r"^" + re.escape(PROPOSAL_EDIT_CALLBACK_PREFIX))


# --------------------------------------------------------------------------
# /ingest/slack payload construction (see luna/api/routes/ingest.py)
# --------------------------------------------------------------------------


def build_slack_ingest_event(
    *,
    event_type: str,
    team_id: str,
    user_id: str,
    display_name: str | None,
    channel_id: str | None = None,
    command_name: str | None = None,
    command_options: dict[str, Any] | None = None,
    modal_custom_id: str | None = None,
    modal_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": event_type,
        "team_id": team_id,
        "channel_id": channel_id,
        "user": {"platform_user_id": user_id, "display_name": display_name},
    }
    if command_name is not None:
        event["command"] = {"name": command_name, "options": command_options or {}}
    if modal_custom_id is not None:
        event["modal"] = {"custom_id": modal_custom_id, "fields": modal_fields or {}}
    return event


# --------------------------------------------------------------------------
# /status modal
# --------------------------------------------------------------------------


def build_status_modal_view() -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": STATUS_MODAL_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Status update"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "issue_key_block",
                "optional": True,
                "label": {"type": "plain_text", "text": "Issue key (leave blank if unsure)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "issue_key",
                    "placeholder": {"type": "plain_text", "text": "C3-142"},
                },
            },
            {
                "type": "input",
                "block_id": "update_text_block",
                "label": {"type": "plain_text", "text": "What's the update?"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "update_text",
                    "multiline": True,
                },
            },
            {
                "type": "input",
                "block_id": "is_blocker_block",
                "optional": True,
                "label": {"type": "plain_text", "text": "Is this blocking you?"},
                "element": {
                    "type": "checkboxes",
                    "action_id": "is_blocker",
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": "Yes, this is blocking me"},
                            "value": "blocked",
                        }
                    ],
                },
            },
        ],
    }


def parse_status_modal_submission(view: dict[str, Any]) -> dict[str, Any]:
    values = view["state"]["values"]
    issue_key = values["issue_key_block"]["issue_key"]["value"]
    update_text = values["update_text_block"]["update_text"]["value"]
    selected = values["is_blocker_block"]["is_blocker"].get("selected_options") or []
    return {
        "issue_key": issue_key or None,
        "update_text": update_text,
        "is_blocker": bool(selected),
    }


async def handle_status_command(ack: Any, body: dict[str, Any], client: Any) -> None:
    await ack()
    await client.views_open(trigger_id=body["trigger_id"], view=build_status_modal_view())


async def handle_status_modal_submission(
    ack: Any, body: dict[str, Any], api_client: LunaAPIClient
) -> dict[str, Any]:
    await ack()
    view = body["view"]
    fields = parse_status_modal_submission(view)
    user = body["user"]
    event = build_slack_ingest_event(
        event_type="modal_submit",
        team_id=body["team"]["id"],
        user_id=user["id"],
        display_name=user.get("username") or user.get("name"),
        command_name="status",
        modal_custom_id=STATUS_MODAL_CALLBACK_ID,
        modal_fields=fields,
    )
    try:
        return await api_client.ingest_slack(event)
    except LunaAPIError:
        logger.exception("status modal ingest failed")
        raise


# --------------------------------------------------------------------------
# Simple (non-modal) slash commands: /ask /standup /blockers /budget /record
# --------------------------------------------------------------------------


async def handle_slash_command(
    ack: Any, body: dict[str, Any], client: Any, api_client: LunaAPIClient, *, command_name: str
) -> dict[str, Any] | None:
    await ack()

    if command_name == "status":
        await client.views_open(trigger_id=body["trigger_id"], view=build_status_modal_view())
        return None

    if command_name == "record":
        # Voice capture is Discord-only (Pycord sinks) -- spec §3.3
        # capability #3. Slack is a mirror surface with no voice pipeline.
        await client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text="Voice recording only works in Discord right now -- run `/record` there.",
        )
        return None

    event = build_slack_ingest_event(
        event_type="slash_command",
        team_id=body["team_id"],
        channel_id=body.get("channel_id"),
        user_id=body["user_id"],
        display_name=body.get("user_name"),
        command_name=command_name,
        command_options={"text": body.get("text", "")},
    )
    try:
        ack_result = await api_client.ingest_slack(event)
    except LunaAPIError:
        logger.exception("%s command ingest failed", command_name)
        await client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text="Sorry, I couldn't reach LUNA's API just now -- try again in a bit.",
        )
        raise
    await client.chat_postEphemeral(
        channel=body["channel_id"],
        user=body["user_id"],
        text=f"On it -- working on your `/{command_name}` request.",
    )
    return ack_result


# --------------------------------------------------------------------------
# Proposal cards: Confirm / Edit / Cancel
# --------------------------------------------------------------------------


def _format_diff(diff: dict[str, Any]) -> str:
    if not diff:
        return "(no fields)"
    lines = []
    for field, change in diff.items():
        if isinstance(change, dict) and ("before" in change or "after" in change):
            lines.append(f"*{field}*: {change.get('before')!r} -> {change.get('after')!r}")
        else:
            lines.append(f"*{field}*: {change!r}")
    return "\n".join(lines)


def build_proposal_blocks(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    """`proposal`: CONTRACT.md's `proposal` table shape --
    `{"id", "kind", "target_jira_key", "diff_json", "confidence", "status"}`."""
    header = f"*Proposed change: {proposal.get('target_jira_key') or '(new issue)'}*"
    fields_text = f"*Kind:* {proposal.get('kind', 'unknown')}"
    confidence = proposal.get("confidence")
    if confidence is not None:
        fields_text += f"\n*Confidence:* {confidence:.0%}"
    proposal_id = str(proposal["id"])
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{header}\n{_format_diff(proposal.get('diff_json', {}))}"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": fields_text}},
        {
            "type": "actions",
            "block_id": f"proposal_actions_{proposal_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Confirm"},
                    "style": "primary",
                    "action_id": "proposal_confirm",
                    "value": proposal_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit"},
                    "action_id": "proposal_edit",
                    "value": proposal_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "style": "danger",
                    "action_id": "proposal_cancel",
                    "value": proposal_id,
                },
            ],
        },
    ]


def build_proposal_edit_modal_view(proposal_id: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": f"{PROPOSAL_EDIT_CALLBACK_PREFIX}{proposal_id}",
        "private_metadata": proposal_id,
        "title": {"type": "plain_text", "text": "Edit proposal"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "edit_block",
                "label": {"type": "plain_text", "text": "Edited value(s)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "edited_fields",
                    "multiline": True,
                },
            }
        ],
    }


async def _respond(respond_url: str | None, text: str) -> None:
    if not respond_url:
        return
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(respond_url, json={"text": text, "replace_original": False})


async def handle_proposal_action(
    ack: Any, body: dict[str, Any], client: Any, api_client: LunaAPIClient, *, action_id: str
) -> None:
    await ack()
    proposal_id = body["actions"][0]["value"]
    respond_url = body.get("response_url")

    if action_id == "proposal_edit":
        trigger_id = body.get("trigger_id")
        if not trigger_id:
            await _respond(respond_url, "Couldn't open the edit form -- try again.")
            return
        await client.views_open(trigger_id=trigger_id, view=build_proposal_edit_modal_view(proposal_id))
        return

    api_call = {
        "proposal_confirm": api_client.confirm_proposal,
        "proposal_cancel": api_client.cancel_proposal,
    }.get(action_id)
    if api_call is None:
        return

    try:
        await api_call(proposal_id)
    except LunaAPIError:
        logger.exception("proposal action %s failed for %s", action_id, proposal_id)
        await _respond(respond_url, "That didn't go through -- try again.")
        return

    message = "Confirmed." if action_id == "proposal_confirm" else "Cancelled."
    await _respond(respond_url, message)


async def handle_proposal_edit_submission(
    ack: Any, body: dict[str, Any], api_client: LunaAPIClient
) -> dict[str, Any]:
    await ack()
    view = body["view"]
    proposal_id = view["private_metadata"]
    edited_text = view["state"]["values"]["edit_block"]["edited_fields"]["value"]
    try:
        return await api_client.edit_proposal(proposal_id, {"raw_text": edited_text})
    except LunaAPIError:
        logger.exception("proposal edit submission failed for %s", proposal_id)
        raise


# --------------------------------------------------------------------------
# App wiring
# --------------------------------------------------------------------------


def build_app() -> Any:
    from slack_bolt.async_app import AsyncApp

    settings = get_settings()
    return AsyncApp(token=settings.slack_bot_token)


def register_handlers(app: Any, api_client: LunaAPIClient) -> None:
    for command_name in SLASH_COMMANDS:

        def _make_command_handler(name: str) -> Any:
            async def _handler(ack: Any, body: dict[str, Any], client: Any) -> None:
                await handle_slash_command(ack, body, client, api_client, command_name=name)

            return _handler

        app.command(f"/{command_name}")(_make_command_handler(command_name))

    async def _status_modal_handler(ack: Any, body: dict[str, Any]) -> None:
        await handle_status_modal_submission(ack, body, api_client)

    app.view(STATUS_MODAL_CALLBACK_ID)(_status_modal_handler)

    async def _edit_submission_handler(ack: Any, body: dict[str, Any]) -> None:
        await handle_proposal_edit_submission(ack, body, api_client)

    app.view(PROPOSAL_EDIT_CALLBACK_PATTERN)(_edit_submission_handler)

    for action_id in ("proposal_confirm", "proposal_cancel", "proposal_edit"):

        def _make_action_handler(aid: str) -> Any:
            async def _handler(ack: Any, body: dict[str, Any], client: Any) -> None:
                await handle_proposal_action(ack, body, client, api_client, action_id=aid)

            return _handler

        app.action(action_id)(_make_action_handler(action_id))
