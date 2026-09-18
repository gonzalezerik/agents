"""DiscordAdapter (CONTRACT.md `luna/adapters/discord_adapter.py`, spec §1.5/§3.8).

## Library choice: py-cord, not discord.py

`py-cord>=2.8` is used instead of `discord.py`. Both expose the same
application-command/modal API surface (they share a common ancestor), but
only py-cord ships `VoiceClient.start_recording(sink, callback)` and the
`discord.sinks` module (`PCMSink`/`WaveSink`/...) that spec §1.5 and
CONTRACT.md's DiscordAdapter section both call out by name for the `/record`
capability -- discord.py's `voice_client` has no recording API at all.
Installed as `py-cord[voice]` (pulls in PyNaCl + davey) so voice connect
actually works; the base `py-cord` install alone does not need those, and
non-voice commands would still work without the extra, but `/record` would
raise `MissingVoiceDependenciesError` at connect time without it.

## Interaction-first, no Message Content intent

Every command here is either a slash command or a modal submission --
`discord.Intents.default()` is used as-is in `build_bot()`, and the
privileged `Message Content` intent is never requested, per spec §1.5
("Modals are the clean way to collect structured status **without** the
privileged Message Content intent") and CONTRACT.md's DiscordAdapter section
("Only request the privileged Message Content intent if a capability
genuinely needs free-text listening outside a modal"). No capability in this
build's scope needs that.

## Modal deviation from CONTRACT.md's sketch

CONTRACT.md describes the `/status` modal as containing "an issue-picker
select populated by calling luna-api". Checked against py-cord 2.8.1's
stable `discord.ui.Modal` API: it accepts only `discord.ui.InputText`
children (short/paragraph text fields) -- no select menu or checkbox
component is legal inside a *stable* Discord modal. (py-cord 2.8 also ships
an unstable `DesignerModal`/Components-v2 API with `Select`/`Checkbox`
modal items, added very recently for Discord's newest, still-rolling-out
modal features; not used here -- too new/unverified for a project a human
can't yet even test against a real bot token, see NOTES.md.) Separately, an
"issue-picker populated by calling luna-api" would need a live
JQL-candidate-search endpoint, which would live in
`capabilities/status_intake.py` + `adapters/jira.py` -- neither exists in
this worktree (out of this build's scope; capability #1's own spec text
says issue matching is itself a Choice decision the Decision Engine makes,
not something this adapter should pre-empt by guessing at candidates).

So `StatusModal` ships three plain `InputText` fields instead:
- `issue_key` (optional free text, e.g. "C3-142"; blank means "let the
  status_intake capability figure out which issue this is about" -- exactly
  spec capability #1's "which issue does this reference? (Choice over
  JQL-retrieved candidates)").
- `update_text` (required, paragraph style -- the free-form status).
- `is_blocker` (required short text, parsed yes/no -- modals have no native
  checkbox/boolean component in the stable API either).

Both `issue_key` and `update_text` are **untrusted** platform text -- see
`luna/api/routes/ingest.py`'s docstring for exactly how/when downstream
capability code must wrap and gate them before they reach a Decision
question's `state` or `Generation.generate()`. This module never calls
either.

## Proposal cards / Confirm-Edit-Cancel

`build_proposal_embed()` + `ProposalActionView` render a `proposal` row
(CONTRACT.md's `proposal` table shape: `id, kind, target_jira_key,
diff_json, confidence, status`) as a Discord embed with three buttons, each
wired to **this same service's own** `POST /proposals/{id}/confirm|cancel|edit`
via `LunaAPIClient` (`luna/adapters/_api_client.py`) -- never a second
source of truth, per CONTRACT.md's "the bot calls its own API" design. That
route belongs to another builder and does not exist in this worktree yet;
button clicks will get a `LunaAPIError` (wrapping a 404) until it lands,
which this module handles the same as any other API failure (log + tell the
user, don't crash).

## Voice recording handoff contract (the seam another builder's
`TranscriptAdapter` is expected to consume)

`/record` toggles a per-guild recording (`_ACTIVE_RECORDINGS`, in-process
state -- fine for a single bot process). On start: joins the invoking user's
current voice channel and calls `voice_client.start_recording(WaveSink(),
callback, ...)`. On stop (second `/record`, or the sink's own finish):

1. For each speaker in `sink.audio_data` (py-cord keys this by Discord user
   id), the raw audio bytes are written to a local temp file
   (`tempfile.mkstemp`) -- CONTRACT.md/spec: "writing raw PCM to a temp
   file". One file per speaker, not one merged file, because capability #3
   (`meeting_action_items`) needs per-speaker audio to answer its own
   *"owner? (Choice over roster)"* decision -- merging streams here would
   throw that attribution away before it's even a capability's problem.
2. Each temp file is uploaded to Garage (S3-compatible; `boto3`, added to
   `pyproject.toml` by this build) under `GARAGE_BUCKET`, key
   `voice/{guild_id}/{channel_id}/{uuid}-{speaker_id}.pcm`
   (`upload_recording_to_garage`). This runs off the event loop
   (`asyncio.to_thread`) since boto3 is synchronous -- spec/CONTRACT.md:
   "don't block the bot's event loop on transcription" (uploading is not
   transcription, but the same rule applies to any slow I/O in this
   process).
3. One `POST /ingest/discord` event per speaker, `type: "voice_recording"`,
   carrying the Garage object key (not a local path -- the temp file is
   deleted right after upload) and basic audio metadata. See
   `luna/api/routes/ingest.py`'s docstring for the exact JSON shape.
4. **What happens after that POST is not this module's problem.** This
   build does not know `TranscriptAdapter`'s real interface (owned by
   another builder, not present in this worktree) or how `luna-worker` will
   discover new recordings to transcribe -- by polling `agent_run` rows with
   `capability="meeting_action_items"` and
   `checkpoint_json.data.type="voice_recording"`, by a dedicated queue, or
   something else is that builder's call. This is the "clean, documented
   seam" CONTRACT.md's task brief asked for, not a new DB table.

If `GARAGE_ENDPOINT`/`GARAGE_ACCESS_KEY_ID`/`GARAGE_SECRET_ACCESS_KEY` are
not fully set, `upload_recording_to_garage` raises `GarageNotConfiguredError`
-- `handle_recording_finished` catches it per speaker, logs a specific
actionable error, and skips that speaker's audio (dropped, not queued)
rather than crashing the bot process. This matches CONTRACT.md's
credential-handling policy: Garage is a feature-specific credential (only
`/record` needs it), not a whole-process-fatal one like `DISCORD_BOT_TOKEN`
(see `luna/entrypoints/discord_bot.py`).

## Testing

No live Discord gateway/voice connection is available or needed to test any
of the logic above -- every `handle_*`/`build_*` function here takes plain
data or a duck-typed stand-in for py-cord's `Interaction`/`Modal`/`View`
objects (the real objects are effectively attribute bags for the fields this
module reads) so `tests/test_adapters_discord.py` calls them directly with
hand-built fakes. `register_commands`/`build_bot` (the actual
`discord.ext.commands.Bot` wiring) are intentionally left untested -- that
part is thin glue with no branches, and there is no way to exercise it
without a live gateway connection.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

from luna.adapters._api_client import LunaAPIClient, LunaAPIError
from luna.config import get_settings

if TYPE_CHECKING:
    import discord.sinks

logger = logging.getLogger("luna.adapters.discord")

SLASH_COMMANDS = ("status", "ask", "standup", "record", "blockers", "budget")

# guild_id (or "dm") -> the VoiceClient currently recording there. In-process
# only; fine for a single bot instance, per this module's docstring.
_ACTIVE_RECORDINGS: dict[str, Any] = {}


# --------------------------------------------------------------------------
# /ingest/discord payload construction (see luna/api/routes/ingest.py)
# --------------------------------------------------------------------------


def build_discord_ingest_event(
    *,
    event_type: str,
    channel_id: str,
    user_id: str,
    display_name: str | None,
    guild_id: str | None = None,
    interaction_id: str | None = None,
    command_name: str | None = None,
    command_options: dict[str, Any] | None = None,
    modal_custom_id: str | None = None,
    modal_fields: dict[str, Any] | None = None,
    voice_recording: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": event_type,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "interaction_id": interaction_id,
        "user": {"platform_user_id": user_id, "display_name": display_name},
    }
    if command_name is not None:
        event["command"] = {"name": command_name, "options": command_options or {}}
    if modal_custom_id is not None:
        event["modal"] = {"custom_id": modal_custom_id, "fields": modal_fields or {}}
    if voice_recording is not None:
        event["voice_recording"] = voice_recording
    return event


def parse_yes_no(raw: str) -> bool:
    return raw.strip().lower() in ("y", "yes", "true", "1")


# --------------------------------------------------------------------------
# /status modal
# --------------------------------------------------------------------------


class StatusModal(discord.ui.Modal):
    """See module docstring "Modal deviation from CONTRACT.md's sketch"."""

    def __init__(self, api_client: LunaAPIClient, *, channel_id: str, guild_id: str | None) -> None:
        super().__init__(title="Status update")
        self.api_client = api_client
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.issue_key_input = discord.ui.InputText(
            label="Issue key (leave blank if unsure)",
            placeholder="C3-142",
            required=False,
            max_length=32,
        )
        self.update_text_input = discord.ui.InputText(
            label="What's the update?",
            style=discord.InputTextStyle.paragraph,
            required=True,
            max_length=1000,
        )
        self.is_blocker_input = discord.ui.InputText(
            label="Is this blocking you? (yes/no)",
            required=True,
            max_length=3,
            value="no",
        )
        self.add_item(self.issue_key_input)
        self.add_item(self.update_text_input)
        self.add_item(self.is_blocker_input)

    async def callback(self, interaction: discord.Interaction) -> None:
        await handle_status_modal_submit(self, interaction)


async def handle_status_modal_submit(
    modal: StatusModal, interaction: discord.Interaction
) -> dict[str, Any]:
    """Separated from `StatusModal.callback` so it's directly unit-testable
    with a hand-built fake `modal`/`interaction` (no live gateway needed)."""
    event = build_discord_ingest_event(
        event_type="modal_submit",
        channel_id=modal.channel_id,
        guild_id=modal.guild_id,
        user_id=str(interaction.user.id),
        display_name=getattr(interaction.user, "display_name", None),
        interaction_id=str(interaction.id),
        command_name="status",
        modal_custom_id="status_modal",
        modal_fields={
            "issue_key": modal.issue_key_input.value or None,
            "update_text": modal.update_text_input.value,
            "is_blocker": parse_yes_no(modal.is_blocker_input.value),
        },
    )
    try:
        ack = await modal.api_client.ingest_discord(event)
    except LunaAPIError:
        logger.exception("status modal ingest failed")
        await interaction.response.send_message(
            "Sorry, I couldn't reach LUNA's API just now -- try again in a bit.",
            ephemeral=True,
        )
        raise
    await interaction.response.send_message(
        "Got it -- I'll turn that into a proposed Jira update shortly.", ephemeral=True
    )
    return ack


# --------------------------------------------------------------------------
# Simple (non-modal) slash commands: /ask /standup /blockers /budget
# --------------------------------------------------------------------------


async def handle_status_command(interaction: discord.Interaction, api_client: LunaAPIClient) -> None:
    modal = StatusModal(
        api_client,
        channel_id=str(interaction.channel_id),
        guild_id=str(interaction.guild_id) if interaction.guild_id else None,
    )
    await interaction.response.send_modal(modal)


async def handle_simple_command(
    interaction: discord.Interaction,
    api_client: LunaAPIClient,
    *,
    command_name: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Shared handler for `/ask`, `/standup`, `/blockers`, `/budget`:
    normalize + POST to /ingest/discord, ack the user ephemerally. `/status`
    (modal) and `/record` (voice) have their own handlers."""
    event = build_discord_ingest_event(
        event_type="slash_command",
        channel_id=str(interaction.channel_id),
        guild_id=str(interaction.guild_id) if interaction.guild_id else None,
        user_id=str(interaction.user.id),
        display_name=getattr(interaction.user, "display_name", None),
        interaction_id=str(interaction.id),
        command_name=command_name,
        command_options=options,
    )
    try:
        ack = await api_client.ingest_discord(event)
    except LunaAPIError:
        logger.exception("%s command ingest failed", command_name)
        await interaction.response.send_message(
            "Sorry, I couldn't reach LUNA's API just now -- try again in a bit.",
            ephemeral=True,
        )
        raise
    await interaction.response.send_message(
        f"On it -- working on your `/{command_name}` request.", ephemeral=True
    )
    return ack


# --------------------------------------------------------------------------
# Proposal cards: Confirm / Edit / Cancel
# --------------------------------------------------------------------------


def _format_diff(diff: dict[str, Any]) -> str:
    if not diff:
        return "(no fields)"
    lines = []
    for field, change in diff.items():
        if isinstance(change, dict) and ("before" in change or "after" in change):
            lines.append(f"**{field}**: {change.get('before')!r} -> {change.get('after')!r}")
        else:
            lines.append(f"**{field}**: {change!r}")
    return "\n".join(lines)


def build_proposal_embed(proposal: dict[str, Any]) -> discord.Embed:
    """`proposal`: CONTRACT.md's `proposal` table shape --
    `{"id", "kind", "target_jira_key", "diff_json", "confidence", "status"}`."""
    embed = discord.Embed(
        title=f"Proposed change: {proposal.get('target_jira_key') or '(new issue)'}",
        description=_format_diff(proposal.get("diff_json", {})),
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Kind", value=str(proposal.get("kind", "unknown")), inline=True)
    confidence = proposal.get("confidence")
    if confidence is not None:
        embed.add_field(name="Confidence", value=f"{confidence:.0%}", inline=True)
    embed.set_footer(text=f"proposal {proposal['id']} -- confirm, edit, or cancel below")
    return embed


class ProposalEditModal(discord.ui.Modal):
    def __init__(self, proposal_id: str, api_client: LunaAPIClient) -> None:
        super().__init__(title="Edit proposal")
        self.proposal_id = proposal_id
        self.api_client = api_client
        self.edited_fields_input = discord.ui.InputText(
            label="Edited value(s)",
            style=discord.InputTextStyle.paragraph,
            placeholder="e.g. status: In Review",
            required=True,
            max_length=1000,
        )
        self.add_item(self.edited_fields_input)

    async def callback(self, interaction: discord.Interaction) -> None:
        await handle_proposal_edit_submit(self, interaction)


async def handle_proposal_edit_submit(
    modal: ProposalEditModal, interaction: discord.Interaction
) -> None:
    try:
        await modal.api_client.edit_proposal(
            modal.proposal_id, {"raw_text": modal.edited_fields_input.value}
        )
    except LunaAPIError:
        logger.exception("proposal edit failed for %s", modal.proposal_id)
        await interaction.response.send_message("That didn't go through -- try again.", ephemeral=True)
        return
    await interaction.response.send_message("Edit submitted.", ephemeral=True)


async def handle_proposal_confirm(
    proposal_id: str, api_client: LunaAPIClient, interaction: discord.Interaction
) -> None:
    try:
        await api_client.confirm_proposal(proposal_id)
    except LunaAPIError:
        logger.exception("proposal confirm failed for %s", proposal_id)
        await interaction.response.send_message("That didn't go through -- try again.", ephemeral=True)
        return
    await interaction.response.send_message("Confirmed.", ephemeral=True)


async def handle_proposal_cancel(
    proposal_id: str, api_client: LunaAPIClient, interaction: discord.Interaction
) -> None:
    try:
        await api_client.cancel_proposal(proposal_id)
    except LunaAPIError:
        logger.exception("proposal cancel failed for %s", proposal_id)
        await interaction.response.send_message("That didn't go through -- try again.", ephemeral=True)
        return
    await interaction.response.send_message("Cancelled.", ephemeral=True)


class ProposalActionView(discord.ui.View):
    """Confirm/Edit/Cancel buttons on a proposal card embed. `custom_id`s are
    fixed strings, not per-proposal, because `self.proposal_id` is bound on
    the view instance itself (one view per posted card) -- `timeout=None`
    keeps the view (and thus the buttons) alive indefinitely, since a
    proposal can sit pending for as long as a human needs."""

    def __init__(self, proposal_id: str, api_client: LunaAPIClient) -> None:
        super().__init__(timeout=None)
        self.proposal_id = proposal_id
        self.api_client = api_client

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, custom_id="proposal_confirm")
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await handle_proposal_confirm(self.proposal_id, self.api_client, interaction)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary, custom_id="proposal_edit")
    async def edit(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ProposalEditModal(self.proposal_id, self.api_client))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="proposal_cancel")
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await handle_proposal_cancel(self.proposal_id, self.api_client, interaction)


# --------------------------------------------------------------------------
# Voice recording (/record) -- see module docstring for the full contract
# --------------------------------------------------------------------------


class GarageNotConfiguredError(RuntimeError):
    """Raised when GARAGE_* credentials aren't fully set. Per CONTRACT.md's
    credential policy this is a feature-specific failure (only `/record`
    needs Garage), not fatal to the whole `luna-discord` process."""


def _garage_client() -> Any:
    import boto3  # local import: only the /record path needs boto3's cost.

    settings = get_settings()
    if not (
        settings.garage_endpoint
        and settings.garage_access_key_id
        and settings.garage_secret_access_key
    ):
        raise GarageNotConfiguredError(
            "GARAGE_ENDPOINT/GARAGE_ACCESS_KEY_ID/GARAGE_SECRET_ACCESS_KEY are not fully set "
            "-- voice recording handoff needs all three to upload captured audio. Set them in "
            "the luna-discord deployment's env/secret (same Garage instance luna-api uses)."
        )
    return boto3.client(
        "s3",
        endpoint_url=settings.garage_endpoint,
        aws_access_key_id=settings.garage_access_key_id,
        aws_secret_access_key=settings.garage_secret_access_key,
        region_name="garage",
    )


async def upload_recording_to_garage(local_path: Path, key: str) -> str:
    """Uploads `local_path` to `GARAGE_BUCKET` under `key`, off the event
    loop (boto3 is synchronous). Returns `key` unchanged for chaining."""
    client = _garage_client()
    settings = get_settings()
    await asyncio.to_thread(client.upload_file, str(local_path), settings.garage_bucket, key)
    return key


async def handle_recording_finished(
    sink: discord.sinks.Sink,
    api_client: LunaAPIClient,
    *,
    channel_id: str,
    guild_id: str | None,
) -> list[dict[str, Any]]:
    """The record -> handoff seam described in the module docstring. Writes
    each speaker's captured audio to a temp file, uploads it to Garage, and
    POSTs one `voice_recording` event per speaker to /ingest/discord.
    Continues past a single speaker's upload/ingest failure rather than
    losing every other speaker's audio over one bad one; returns the list of
    successful ingest acks (mainly useful for tests)."""
    acks: list[dict[str, Any]] = []
    speaker_count = len(sink.audio_data)
    for user_id, audio in sink.audio_data.items():
        fd, tmp_name = tempfile.mkstemp(suffix=".pcm", prefix="luna-voice-")
        tmp_path = Path(tmp_name)
        try:
            import os

            with os.fdopen(fd, "wb") as fh:
                fh.write(audio.file.read())

            garage_key = f"voice/{guild_id or 'dm'}/{channel_id}/{uuid.uuid4().hex}-{user_id}.pcm"
            try:
                await upload_recording_to_garage(tmp_path, garage_key)
            except GarageNotConfiguredError:
                logger.error(
                    "voice recording captured for discord user=%s but Garage isn't configured "
                    "-- audio dropped, not handed off for transcription. See "
                    "GarageNotConfiguredError's message for what to set.",
                    user_id,
                )
                continue

            event = build_discord_ingest_event(
                event_type="voice_recording",
                channel_id=channel_id,
                guild_id=guild_id,
                user_id=str(user_id),
                display_name=None,
                voice_recording={
                    "garage_key": garage_key,
                    "duration_seconds": None,
                    "sample_rate_hz": 48000,
                    "channels": 2,
                    "speaker_count": speaker_count,
                },
            )
            try:
                ack = await api_client.ingest_discord(event)
            except LunaAPIError:
                logger.exception(
                    "voice recording uploaded (key=%s) but /ingest/discord failed -- "
                    "recording is in Garage but no agent_run was created for it",
                    garage_key,
                )
                continue
            acks.append(ack)
        finally:
            tmp_path.unlink(missing_ok=True)
    return acks


def _recording_finished_callback(
    api_client: LunaAPIClient, *, channel_id: str, guild_id: str | None
) -> Any:
    async def _finished(sink: discord.sinks.Sink, *_args: Any) -> None:
        try:
            await handle_recording_finished(
                sink, api_client, channel_id=channel_id, guild_id=guild_id
            )
        finally:
            vc = getattr(sink, "vc", None)
            if vc is not None:
                await vc.disconnect()

    return _finished


async def handle_record_command(interaction: discord.Interaction, api_client: LunaAPIClient) -> None:
    guild_id = str(interaction.guild_id) if interaction.guild_id else None
    key = guild_id or "dm"

    if key in _ACTIVE_RECORDINGS:
        _ACTIVE_RECORDINGS.pop(key).stop_recording()
        await interaction.response.send_message(
            "Stopping recording -- I'll hand it off for transcription.", ephemeral=True
        )
        return

    voice_state = getattr(interaction.user, "voice", None)
    if voice_state is None or voice_state.channel is None:
        await interaction.response.send_message(
            "Join a voice channel first, then run `/record`.", ephemeral=True
        )
        return

    voice_client = await voice_state.channel.connect()
    sink = discord.sinks.WaveSink()
    channel_id = str(interaction.channel_id)
    voice_client.start_recording(
        sink,
        _recording_finished_callback(api_client, channel_id=channel_id, guild_id=guild_id),
        interaction.channel,
    )
    _ACTIVE_RECORDINGS[key] = voice_client
    await interaction.response.send_message(
        "Recording started -- run `/record` again to stop.", ephemeral=True
    )


# --------------------------------------------------------------------------
# Bot wiring
# --------------------------------------------------------------------------


def build_bot() -> commands.Bot:
    intents = discord.Intents.default()
    return commands.Bot(intents=intents)


def register_commands(bot: commands.Bot, api_client: LunaAPIClient) -> None:
    @bot.slash_command(name="status", description="Post a structured status update")
    async def status_cmd(ctx: discord.ApplicationContext) -> None:
        await handle_status_command(ctx.interaction, api_client)

    @bot.slash_command(name="ask", description="Ask LUNA a question about the project")
    async def ask_cmd(
        ctx: discord.ApplicationContext,
        question: discord.Option(str, "Your question"),  # type: ignore[valid-type]
    ) -> None:
        await handle_simple_command(
            ctx.interaction, api_client, command_name="ask", options={"question": question}
        )

    @bot.slash_command(name="standup", description="Request the latest standup summary")
    async def standup_cmd(ctx: discord.ApplicationContext) -> None:
        await handle_simple_command(ctx.interaction, api_client, command_name="standup", options={})

    @bot.slash_command(
        name="record", description="Start/stop recording this voice channel for meeting notes"
    )
    async def record_cmd(ctx: discord.ApplicationContext) -> None:
        await handle_record_command(ctx.interaction, api_client)

    @bot.slash_command(name="blockers", description="List current cross-subteam blockers")
    async def blockers_cmd(ctx: discord.ApplicationContext) -> None:
        await handle_simple_command(ctx.interaction, api_client, command_name="blockers", options={})

    @bot.slash_command(name="budget", description="Show current budget/margin status")
    async def budget_cmd(ctx: discord.ApplicationContext) -> None:
        await handle_simple_command(ctx.interaction, api_client, command_name="budget", options={})
