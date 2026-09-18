"""Tests for luna/adapters/discord_adapter.py.

No live Discord gateway/voice connection is used. `discord.ui.Modal`/`View`
subclasses need a running asyncio loop to construct (py-cord's `core.py`
calls `asyncio.get_running_loop()`), which every test here has via
`asyncio_mode = "auto"` -- otherwise these are all plain function calls with
hand-built fakes, per discord_adapter.py's own "Testing" docstring section.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import discord
import pytest

from luna.adapters import discord_adapter as da
from luna.adapters._api_client import LunaAPIError


class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.modals: list[object] = []

    async def send_message(self, content: str | None = None, *, ephemeral: bool = False, **_kw) -> None:
        self.messages.append({"content": content, "ephemeral": ephemeral})

    async def send_modal(self, modal: object) -> None:
        self.modals.append(modal)


class FakeUser:
    def __init__(self, user_id: int, display_name: str | None = "Erik", voice=None) -> None:
        self.id = user_id
        self.display_name = display_name
        self.voice = voice


class FakeInteraction:
    def __init__(self, *, user: FakeUser, channel_id: int = 111, guild_id: int | None = 222, iid: int = 333) -> None:
        self.user = user
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.id = iid
        self.response = FakeResponse()


# --------------------------------------------------------------------------
# build_discord_ingest_event / parse_yes_no
# --------------------------------------------------------------------------


def test_build_discord_ingest_event_slash_command_shape() -> None:
    event = da.build_discord_ingest_event(
        event_type="slash_command",
        channel_id="1",
        user_id="2",
        display_name="Erik",
        guild_id="3",
        interaction_id="4",
        command_name="ask",
        command_options={"question": "what's blocked?"},
    )
    assert event == {
        "type": "slash_command",
        "guild_id": "3",
        "channel_id": "1",
        "interaction_id": "4",
        "user": {"platform_user_id": "2", "display_name": "Erik"},
        "command": {"name": "ask", "options": {"question": "what's blocked?"}},
    }
    assert "modal" not in event
    assert "voice_recording" not in event


def test_build_discord_ingest_event_voice_recording_shape() -> None:
    event = da.build_discord_ingest_event(
        event_type="voice_recording",
        channel_id="1",
        user_id="2",
        display_name=None,
        guild_id="3",
        voice_recording={"garage_key": "voice/3/1/x.pcm", "sample_rate_hz": 48000, "channels": 2},
    )
    assert event["voice_recording"]["garage_key"] == "voice/3/1/x.pcm"
    assert "command" not in event


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("yes", True), ("Y", True), ("true", True), ("1", True), ("no", False), ("", False), ("nah", False)],
)
def test_parse_yes_no(raw: str, expected: bool) -> None:
    assert da.parse_yes_no(raw) is expected


# --------------------------------------------------------------------------
# /status modal
# --------------------------------------------------------------------------


async def test_status_modal_submit_posts_expected_ingest_event() -> None:
    api_client = AsyncMock()
    api_client.ingest_discord.return_value = {"run_id": "abc", "capability": "status_intake", "status": "completed"}

    modal = da.StatusModal(api_client, channel_id="111", guild_id="222")
    modal.issue_key_input.value = "C3-142"
    modal.update_text_input.value = "Finished the wiring harness"
    modal.is_blocker_input.value = "no"

    interaction = FakeInteraction(user=FakeUser(999))
    ack = await da.handle_status_modal_submit(modal, interaction)

    assert ack["capability"] == "status_intake"
    api_client.ingest_discord.assert_awaited_once()
    sent_event = api_client.ingest_discord.await_args.args[0]
    assert sent_event["type"] == "modal_submit"
    assert sent_event["command"] == {"name": "status", "options": {}}
    assert sent_event["modal"]["custom_id"] == "status_modal"
    assert sent_event["modal"]["fields"] == {
        "issue_key": "C3-142",
        "update_text": "Finished the wiring harness",
        "is_blocker": False,
    }
    assert sent_event["user"]["platform_user_id"] == "999"
    assert interaction.response.messages[0]["ephemeral"] is True


async def test_status_modal_submit_blank_issue_key_becomes_none() -> None:
    api_client = AsyncMock()
    api_client.ingest_discord.return_value = {}
    modal = da.StatusModal(api_client, channel_id="111", guild_id="222")
    modal.issue_key_input.value = ""
    modal.update_text_input.value = "update"
    modal.is_blocker_input.value = "yes"

    await da.handle_status_modal_submit(modal, FakeInteraction(user=FakeUser(1)))

    sent_event = api_client.ingest_discord.await_args.args[0]
    assert sent_event["modal"]["fields"]["issue_key"] is None
    assert sent_event["modal"]["fields"]["is_blocker"] is True


async def test_status_modal_submit_ingest_failure_tells_user_and_reraises() -> None:
    api_client = AsyncMock()
    api_client.ingest_discord.side_effect = LunaAPIError("boom")
    modal = da.StatusModal(api_client, channel_id="111", guild_id="222")
    modal.issue_key_input.value = ""
    modal.update_text_input.value = "update"
    modal.is_blocker_input.value = "no"
    interaction = FakeInteraction(user=FakeUser(1))

    with pytest.raises(LunaAPIError):
        await da.handle_status_modal_submit(modal, interaction)

    assert "couldn't reach" in interaction.response.messages[0]["content"]


# --------------------------------------------------------------------------
# Simple slash commands
# --------------------------------------------------------------------------


async def test_handle_simple_command_acks_and_ingests() -> None:
    api_client = AsyncMock()
    api_client.ingest_discord.return_value = {"run_id": "x", "capability": "blocker_dependency", "status": "completed"}
    interaction = FakeInteraction(user=FakeUser(42))

    await da.handle_simple_command(interaction, api_client, command_name="blockers", options={})

    sent_event = api_client.ingest_discord.await_args.args[0]
    assert sent_event["command"]["name"] == "blockers"
    assert "/blockers" in interaction.response.messages[0]["content"]


async def test_handle_simple_command_ingest_failure_reraises() -> None:
    api_client = AsyncMock()
    api_client.ingest_discord.side_effect = LunaAPIError("down")
    interaction = FakeInteraction(user=FakeUser(42))

    with pytest.raises(LunaAPIError):
        await da.handle_simple_command(interaction, api_client, command_name="budget", options={})


# --------------------------------------------------------------------------
# Proposal cards
# --------------------------------------------------------------------------


def test_build_proposal_embed_renders_diff_and_confidence() -> None:
    proposal = {
        "id": "p1",
        "kind": "status_update",
        "target_jira_key": "C3-142",
        "diff_json": {"status": {"before": "To Do", "after": "In Progress"}},
        "confidence": 0.87,
    }
    embed = da.build_proposal_embed(proposal)
    assert isinstance(embed, discord.Embed)
    assert "C3-142" in embed.title
    assert "To Do" in embed.description and "In Progress" in embed.description
    field_names = [f.name for f in embed.fields]
    assert "Kind" in field_names and "Confidence" in field_names


def test_build_proposal_embed_handles_missing_target_key() -> None:
    proposal = {"id": "p2", "kind": "new_issue", "target_jira_key": None, "diff_json": {}}
    embed = da.build_proposal_embed(proposal)
    assert "(new issue)" in embed.title
    assert embed.description == "(no fields)"


async def test_handle_proposal_confirm_success() -> None:
    api_client = AsyncMock()
    interaction = FakeInteraction(user=FakeUser(1))
    await da.handle_proposal_confirm("p1", api_client, interaction)
    api_client.confirm_proposal.assert_awaited_once_with("p1")
    assert interaction.response.messages[0]["content"] == "Confirmed."


async def test_handle_proposal_cancel_api_failure_does_not_raise() -> None:
    api_client = AsyncMock()
    api_client.cancel_proposal.side_effect = LunaAPIError("nope")
    interaction = FakeInteraction(user=FakeUser(1))
    await da.handle_proposal_cancel("p1", api_client, interaction)
    assert "didn't go through" in interaction.response.messages[0]["content"]


async def test_proposal_edit_submit_sends_raw_text() -> None:
    api_client = AsyncMock()
    modal = da.ProposalEditModal("p1", api_client)
    modal.edited_fields_input.value = "status: In Review"
    interaction = FakeInteraction(user=FakeUser(1))

    await da.handle_proposal_edit_submit(modal, interaction)

    api_client.edit_proposal.assert_awaited_once_with("p1", {"raw_text": "status: In Review"})
    assert interaction.response.messages[0]["content"] == "Edit submitted."


# --------------------------------------------------------------------------
# Voice recording handoff
# --------------------------------------------------------------------------


class FakeAudioFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeAudioData:
    def __init__(self, data: bytes) -> None:
        self.file = FakeAudioFile(data)


class FakeSink:
    def __init__(self, audio_data: dict) -> None:
        self.audio_data = audio_data


async def test_handle_recording_finished_uploads_and_ingests_per_speaker(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = FakeSink({111: FakeAudioData(b"pcm-a"), 222: FakeAudioData(b"pcm-b")})
    api_client = AsyncMock()
    api_client.ingest_discord.return_value = {"run_id": "r", "capability": "meeting_action_items"}

    uploaded_keys: list[str] = []

    async def fake_upload(local_path, key):  # noqa: ANN001
        uploaded_keys.append(key)
        return key

    monkeypatch.setattr(da, "upload_recording_to_garage", fake_upload)

    acks = await da.handle_recording_finished(sink, api_client, channel_id="1", guild_id="2")

    assert len(uploaded_keys) == 2
    assert all(k.startswith("voice/2/1/") for k in uploaded_keys)
    assert len(acks) == 2
    assert api_client.ingest_discord.await_count == 2
    for call in api_client.ingest_discord.await_args_list:
        event = call.args[0]
        assert event["type"] == "voice_recording"
        assert event["voice_recording"]["speaker_count"] == 2


async def test_handle_recording_finished_skips_speaker_on_garage_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = FakeSink({111: FakeAudioData(b"pcm-a")})
    api_client = AsyncMock()

    async def fake_upload(local_path, key):  # noqa: ANN001
        raise da.GarageNotConfiguredError("nope")

    monkeypatch.setattr(da, "upload_recording_to_garage", fake_upload)

    acks = await da.handle_recording_finished(sink, api_client, channel_id="1", guild_id="2")

    assert acks == []
    api_client.ingest_discord.assert_not_awaited()


async def test_upload_recording_to_garage_raises_when_unconfigured() -> None:
    from pathlib import Path

    with pytest.raises(da.GarageNotConfiguredError):
        await da.upload_recording_to_garage(Path("/tmp/does-not-matter.pcm"), "voice/x.pcm")
