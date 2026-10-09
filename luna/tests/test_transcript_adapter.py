"""Tests for `luna.adapters.transcript.TranscriptAdapter`.

The actual `faster-whisper` model load/inference is mocked in every test
below -- not because model downloads don't work in this environment (they
do: a real `WhisperModel("tiny", device="cpu", compute_type="int8")` load
was verified here directly during development, completing in ~6s including
the first-use download), but because pulling a real model and running real
inference on every `pytest` invocation would make the default (non-`llm`,
non-live-service) test run slow and network-dependent -- the default suite
must run with no live Jira/Discord/Slack/LLM. See `luna/adapters/transcript.py`'s module
docstring for the full finding.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from luna.adapters.transcript import TranscriptAdapter, TranscriptAdapterError
from luna.config import Settings


class _FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


def _fake_whisper_model(segments: list[_FakeSegment]) -> MagicMock:
    model = MagicMock()
    model.transcribe.return_value = (segments, MagicMock(language="en"))
    return model


async def test_transcribe_file_returns_segmented_text(tmp_path: Path) -> None:
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"not-really-audio")  # existence is all transcribe_file checks

    fake_model = _fake_whisper_model(
        [
            _FakeSegment(0.0, 2.5, "  Let's start the standup.  "),
            _FakeSegment(2.5, 10.0, "Chassis team finished the wiring harness."),
        ]
    )

    adapter = TranscriptAdapter(model_size="tiny")
    with patch.object(adapter, "_get_model", return_value=fake_model):
        segments = await adapter.transcribe_file(audio)

    assert segments == [
        {"start": 0.0, "end": 2.5, "text": "Let's start the standup.", "speaker": None},
        {"start": 2.5, "end": 10.0, "text": "Chassis team finished the wiring harness.", "speaker": None},
    ]
    fake_model.transcribe.assert_called_once()


async def test_transcribe_file_missing_path_raises() -> None:
    adapter = TranscriptAdapter(model_size="tiny")
    with pytest.raises(TranscriptAdapterError):
        await adapter.transcribe_file("/nonexistent/path/does-not-exist.wav")


async def test_transcribe_object_without_garage_credentials_raises_clearly() -> None:
    adapter = TranscriptAdapter(model_size="tiny")
    settings = Settings(
        garage_endpoint="", garage_access_key_id="", garage_secret_access_key=""
    )
    with pytest.raises(TranscriptAdapterError, match="GARAGE_ENDPOINT"):
        await adapter.transcribe_object(key="meetings/2026-09-18.wav", settings=settings)


async def test_transcribe_object_downloads_then_transcribes(tmp_path: Path) -> None:
    fake_model = _fake_whisper_model([_FakeSegment(0.0, 1.0, "hello")])
    adapter = TranscriptAdapter(model_size="tiny")
    settings = Settings(
        garage_endpoint="http://garage.local:3900",
        garage_access_key_id="AKIA_FAKE",
        garage_secret_access_key="fake-secret",
        garage_bucket="luna-artifacts",
    )

    def fake_download(settings_arg, key, dest_path: Path) -> None:
        dest_path.write_bytes(b"downloaded-audio-bytes")

    with (
        patch.object(adapter, "_get_model", return_value=fake_model),
        patch("luna.adapters.transcript._download_from_garage", side_effect=fake_download) as dl,
    ):
        segments = await adapter.transcribe_object(key="meetings/x.wav", settings=settings)

    assert segments == [{"start": 0.0, "end": 1.0, "text": "hello", "speaker": None}]
    dl.assert_called_once()
    called_key = dl.call_args.args[1]
    assert called_key == "meetings/x.wav"


def test_speaker_is_always_none_documented_gap() -> None:
    """No diarization in v1 -- see module docstring. This test exists so the
    invariant is enforced by CI, not just prose."""
    fake_model = _fake_whisper_model([_FakeSegment(0.0, 1.0, "hi")])
    adapter = TranscriptAdapter(model_size="tiny")
    with patch.object(adapter, "_get_model", return_value=fake_model):
        segments = adapter._transcribe_sync(Path("/dev/null"))
    assert all(seg["speaker"] is None for seg in segments)
