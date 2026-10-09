"""`POST /ingest/discord`, `POST /ingest/slack` (CONTRACT.md API surface).

This is the receiving side of the chat layer: `luna/adapters/discord_adapter.py`
and `luna/adapters/slack_adapter.py` are the only intended callers (their own
bot processes calling back into their own API, per CONTRACT.md's "the bot
calls its own API, not the other way around, to keep one source of truth for
proposal state"). Auth is the same shared-secret bearer token as every other
route (`require_service_token`) -- there is nothing platform-specific about
auth here, Discord/Slack signature verification happens in the adapters
themselves before they ever call this API.

## What this route does NOT do

- It does not call `DecisionProvider.decide()` or `Generation.generate()`.
  That is capability code's job (`luna/capabilities/*.py`, another builder's
  scope, not present in this worktree yet).
- It does not wrap inbound text in `guardrails.Untrusted[str]`. That wrapper
  is a frozen dataclass, not JSON-serializable, and `RunContext.data` must
  round-trip through JSON (it is persisted verbatim into
  `agent_run.checkpoint_json` by `control_loop.py`). Instead, every field
  that carries platform-originated free text is documented below as
  untrusted; it is capability code's responsibility, the moment it reads
  such a field back out of `agent_run.checkpoint_json`/`RunContext.data`, to
  call `guardrails.untrusted(value, source=...)` and run
  `guardrails.build_injection_gate_question()` /
  `guardrails.is_injection_flagged()` on it before it reaches a Decision
  question's `state` or `Generation.generate()`. **Untrusted fields in the
  shapes below:** `command.options` (values), `modal.fields` (values).
- It does not resolve a platform user id to a `Roster` row. The `Roster` seed
  (owned by the Jira-adapter builder) currently ships real names with empty
  `discord_id`/`slack_id` for everyone -- there is nothing to resolve against
  yet. `actor_user` on the created `agent_run` is therefore a raw
  platform-prefixed id string (`"discord:<snowflake>"` /
  `"slack:<user id>"`), not a roster name or `roster.user_id`. The documented
  path to fill the mapping in later is a `/link` slash command (a user runs
  it once, in either adapter, to write their platform id onto their own
  `roster` row) or an admin backfill step -- neither is implemented in this
  build; resolving `actor_user` to a roster row is downstream capability
  work.

## What this route DOES do

Validates the inbound event against a small Pydantic shape (below), then
starts a `control_loop.run()` with `capability` resolved from the slash
command name (or `"meeting_action_items"` for a voice-recording handoff) and
`initial_data` set to the normalized event. Because no `luna/capabilities/*`
module exists in this worktree yet, every control-loop node is
`control_loop`'s documented no-op passthrough, so the run completes
trivially (`status="completed"`) with nothing done -- that is expected, not a
bug: the moment a capability module registers real `Ingest`/`Normalize`/...
node functions for these capability names, the exact same POST body starts
doing real work with zero changes needed here. One `audit_event` row is
written per accepted ingest event (`action="ingest.discord.<type>"` /
`"ingest.slack.<type>"`) so "did we ever receive this" is answerable from the
audit log even before any capability logic exists.

## Exact JSON request shapes (other builders' capability code depends on
these -- do not change without updating CONTRACT.md and this docstring)

`POST /ingest/discord`:
```json
{
  "type": "slash_command" | "modal_submit" | "voice_recording",
  "guild_id": "123" | null,
  "channel_id": "456",
  "interaction_id": "789" | null,
  "user": {"platform_user_id": "111", "display_name": "Erik" | null},
  "command": {"name": "status", "options": {"free_text": "..."}} | null,
  "modal": {"custom_id": "status_modal", "fields": {"issue_key": "C3-12", "update_text": "...", "is_blocker": false}} | null,
  "voice_recording": {"garage_key": "voice/456/789.pcm", "duration_seconds": 612.4, "sample_rate_hz": 48000, "channels": 2, "speaker_count": 3} | null
}
```
Slash-command names currently routed: `status` -> `status_intake`,
`ask` -> `rag_qna`, `standup` -> `standup`, `record` -> `meeting_action_items`,
`blockers` -> `blocker_dependency`, `budget` -> `budget_watcher`,
`risks` -> `risk_manager`.
`modal_submit` events must carry both `command` (the originating slash
command) and `modal`. `voice_recording` events are the `/record` handoff --
see `luna/adapters/discord_adapter.py`'s module docstring for the full
recording -> Garage upload -> ingest contract; `garage_key` is the object key
in `GARAGE_BUCKET`, not a local file path (local temp files are cleaned up by
the adapter after a successful upload).

`POST /ingest/slack`: identical shape minus `guild_id`/`voice_recording`,
plus `team_id`:
```json
{
  "type": "slash_command" | "modal_submit",
  "team_id": "T0123",
  "channel_id": "C0456" | null,
  "user": {"platform_user_id": "U0789", "display_name": "Erik" | null},
  "command": {"name": "status", "options": {}} | null,
  "modal": {"custom_id": "status_modal", "fields": {}} | null
}
```

Both routes respond `202 Accepted` with
`{"run_id": "<uuid>", "capability": "status_intake", "status": "completed"}`
on success. Confirm/Edit/Cancel button clicks on proposal cards do **not**
come through here -- both adapters call `POST /proposals/{id}/confirm|cancel|edit`
directly (another builder's route, not yet present in this worktree).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from luna.api.deps import get_db, require_service_token
from luna.audit import write_event
from luna.capabilities._session import run_with_session as run_control_loop

logger = logging.getLogger("luna.api.ingest")

router = APIRouter(prefix="/ingest", tags=["ingest"], dependencies=[Depends(require_service_token)])


# Slash-command name -> `luna/capabilities/*.py` module name (CONTRACT.md
# repo layout), i.e. the `capability` string `control_loop.run()` uses to
# look up registered nodes. Shared between Discord and Slack since both
# adapters mirror the same command set (CONTRACT.md: Slack is a
# secondary/mirror surface, spec §3.1 pushback #4).
COMMAND_TO_CAPABILITY: dict[str, str] = {
    "status": "status_intake",
    "ask": "rag_qna",
    "standup": "standup",
    "record": "meeting_action_items",
    "blockers": "blocker_dependency",
    "budget": "budget_watcher",
    "risks": "risk_manager",
}

VOICE_RECORDING_CAPABILITY = "meeting_action_items"


class PlatformUser(BaseModel):
    platform_user_id: str
    display_name: str | None = None


class SlashCommand(BaseModel):
    name: str
    options: dict[str, Any] = Field(default_factory=dict)


class ModalSubmission(BaseModel):
    custom_id: str
    fields: dict[str, Any] = Field(default_factory=dict)


class VoiceRecordingMeta(BaseModel):
    """See `luna/adapters/discord_adapter.py` for how `garage_key` is
    produced (temp PCM file -> Garage upload -> this metadata)."""

    garage_key: str
    duration_seconds: float | None = None
    sample_rate_hz: int = 48000
    channels: int = 2
    speaker_count: int | None = None


class DiscordIngestEvent(BaseModel):
    type: Literal["slash_command", "modal_submit", "voice_recording"]
    guild_id: str | None = None
    channel_id: str
    interaction_id: str | None = None
    user: PlatformUser
    command: SlashCommand | None = None
    modal: ModalSubmission | None = None
    voice_recording: VoiceRecordingMeta | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> DiscordIngestEvent:
        if self.type in ("slash_command", "modal_submit") and self.command is None:
            raise ValueError(f"{self.type} events require `command`")
        if self.type == "modal_submit" and self.modal is None:
            raise ValueError("modal_submit events require `modal`")
        if self.type == "voice_recording" and self.voice_recording is None:
            raise ValueError("voice_recording events require `voice_recording`")
        return self


class SlackIngestEvent(BaseModel):
    type: Literal["slash_command", "modal_submit"]
    team_id: str
    channel_id: str | None = None
    user: PlatformUser
    command: SlashCommand | None = None
    modal: ModalSubmission | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> SlackIngestEvent:
        if self.command is None:
            raise ValueError(f"{self.type} events require `command`")
        if self.type == "modal_submit" and self.modal is None:
            raise ValueError("modal_submit events require `modal`")
        return self


class IngestAck(BaseModel):
    run_id: uuid.UUID
    capability: str
    status: str
    result: dict[str, Any] | None = None
    """Populated from `ctx.data` for capabilities whose `decide` node produces
    a user-facing answer synchronously within this same request (`rag_qna`,
    `standup`) -- since `control_loop.run()` is awaited in-process with no
    real background queue, the result is already known by the time this
    response is built. `None` for every other capability (proposal-producing
    or purely read/alert capabilities with nothing to show inline). A real
    integration gap found and fixed while wiring the chat and knowledge
    layers together: the Discord/Slack `/ask` and `/standup` commands were
    routing through here and getting back nothing but a generic "on it" ack
    with no way to ever see the actual answer -- see
    `luna/capabilities/rag_qna.py` and `standup.py`'s `decide` node
    registrations, and `discord_adapter.py`/`slack_adapter.py`'s
    `handle_simple_command`, which now sends a follow-up message when this
    field is present."""


# Which `ctx.data` keys to surface as `IngestAck.result` per capability --
# an explicit allowlist rather than dumping all of `ctx.data` (which also
# carries the raw inbound event payload, not just the capability's output).
_RESULT_KEYS: dict[str, tuple[str, ...]] = {
    "rag_qna": ("answer", "citations", "sufficient"),
    "standup": ("team_summary", "member_count", "action_item_proposal_ids"),
    "risk_manager": ("summary_markdown", "findings", "milestones", "proposal_ids"),
}


def _extract_result(capability: str, data: dict[str, Any]) -> dict[str, Any] | None:
    keys = _RESULT_KEYS.get(capability)
    if not keys:
        return None
    return {k: data[k] for k in keys if k in data}


def _resolve_capability(*, event_type: str, command_name: str | None) -> str:
    if event_type == "voice_recording":
        return VOICE_RECORDING_CAPABILITY
    if command_name is None or command_name not in COMMAND_TO_CAPABILITY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unrouted command {command_name!r}; known commands: "
            f"{sorted(COMMAND_TO_CAPABILITY)}",
        )
    return COMMAND_TO_CAPABILITY[command_name]


async def _run_control_loop_or_503(
    session: AsyncSession,
    *,
    capability: str,
    trigger_source: str,
    actor_user: str,
    event_type: str,
    initial_data: dict[str, Any],
):
    """Wraps `control_loop.run()` so a registered node's failure (most
    commonly a not-yet-configured integration, e.g. `JiraNotConfiguredError`
    from a Jira-backed capability with no real site/credentials yet) becomes
    a clean 503 response instead of an unhandled 500.

    `control_loop._drive()` already marks the `agent_run` row `failed` and
    persists `ctx.error` before re-raising -- that part of the audit trail
    is intact regardless of this wrapper. What was missing (a real gap this
    integration found: the ingest routes were built before any capability
    module existed to register a node that could actually fail) is turning
    that re-raised exception into something an API client -- the Discord/Slack
    bot processes -- can show a human instead of a bare 500. We deliberately
    still write an `audit_event` for the failure (unlike the happy path,
    which the caller does after this returns) so every ingest attempt is
    audited whether it succeeds or not.
    """
    try:
        return await run_control_loop(
            session,
            capability=capability,
            trigger_source=trigger_source,
            actor_user=actor_user,
            initial_data=initial_data,
        )
    except Exception as exc:  # noqa: BLE001 - translate any node failure into a 503
        logger.warning(
            "ingest.%s capability=%s failed: %s", trigger_source, capability, exc
        )
        await write_event(
            session,
            actor=actor_user,
            action=f"ingest.{trigger_source}.{event_type}.failed",
            result_ref=f"capability={capability} error={exc}",
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{capability} is not available yet: {exc}",
        ) from exc


@router.post("/discord", response_model=IngestAck, status_code=status.HTTP_202_ACCEPTED)
async def ingest_discord(
    event: DiscordIngestEvent, session: AsyncSession = Depends(get_db)
) -> IngestAck:
    command_name = event.command.name if event.command else None
    capability = _resolve_capability(event_type=event.type, command_name=command_name)
    actor_user = f"discord:{event.user.platform_user_id}"

    ctx = await _run_control_loop_or_503(
        session,
        capability=capability,
        trigger_source="discord",
        actor_user=actor_user,
        event_type=event.type,
        initial_data={"platform": "discord", **event.model_dump(mode="json")},
    )
    await write_event(
        session,
        actor=actor_user,
        action=f"ingest.discord.{event.type}",
        run_id=ctx.run_id,
        result_ref=f"capability={capability}",
    )
    await session.commit()
    logger.info("ingest.discord accepted run_id=%s capability=%s", ctx.run_id, capability)
    return IngestAck(
        run_id=ctx.run_id,
        capability=capability,
        status=ctx.status.value,
        result=_extract_result(capability, ctx.data),
    )


@router.post("/slack", response_model=IngestAck, status_code=status.HTTP_202_ACCEPTED)
async def ingest_slack(
    event: SlackIngestEvent, session: AsyncSession = Depends(get_db)
) -> IngestAck:
    command_name = event.command.name if event.command else None
    capability = _resolve_capability(event_type=event.type, command_name=command_name)
    actor_user = f"slack:{event.user.platform_user_id}"

    ctx = await _run_control_loop_or_503(
        session,
        capability=capability,
        trigger_source="slack",
        actor_user=actor_user,
        event_type=event.type,
        initial_data={"platform": "slack", **event.model_dump(mode="json")},
    )
    await write_event(
        session,
        actor=actor_user,
        action=f"ingest.slack.{event.type}",
        run_id=ctx.run_id,
        result_ref=f"capability={capability}",
    )
    await session.commit()
    logger.info("ingest.slack accepted run_id=%s capability=%s", ctx.run_id, capability)
    return IngestAck(
        run_id=ctx.run_id,
        capability=capability,
        status=ctx.status.value,
        result=_extract_result(capability, ctx.data),
    )
