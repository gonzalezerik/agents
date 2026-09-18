"""`TranscriptAdapter` -- local `faster-whisper` batch transcription (spec
§3.8, CONTRACT.md adapters section).

CONTRACT.md: "batch only for v1... Runs as a job in `luna-worker`, not
inline in the Discord process (voice recording can be long; don't block the
bot's event loop on transcription)." Per this build's explicit scope,
`luna/workers/` belongs to another builder and does not exist in this
worktree -- this module is deliberately **not** wired to any queue/worker
runtime. `transcribe_file()`/`transcribe_object()` are plain `async def`
methods a job runner can call directly (e.g.
`await TranscriptAdapter().transcribe_file(path)`); `faster-whisper`'s
actual inference call is synchronous/CPU-bound, so it's run via
`asyncio.to_thread` internally to avoid blocking the event loop it's called
from, but there is no dispatch/retry/queueing logic here -- that's the
worker's job.

## Model download -- verified against this environment (2026-09-18)

`faster-whisper` lazily downloads a CTranslate2-converted Whisper model from
Hugging Face on first use (there are no bundled weights). This environment
**does** have normal internet egress: a real `WhisperModel("tiny", ...)`
load (which triggers the download) was tested here and completed in ~6s.
This is a real, tested capability of this environment, not a documented gap
-- but it is still a **runtime concern for whatever environment actually
runs `luna-worker` in production** (the cluster's network policy for that
namespace was not verified here, and a cold download adds real latency to
the very first transcription job after a pod restart unless the model
cache -- `HF_HOME`/`XDG_CACHE_HOME`, or `download_root` below -- is a
persistent volume). Document a model warm-up step or a persistent cache
mount in the `luna-worker` Deployment; this module does not attempt to
solve that (out of scope -- `deploy/` isn't owned by this build).

Model size defaults to `"base"` (CONTRACT.md/spec's suggested example, a
reasonable accuracy/latency tradeoff for meeting-length audio on CPU); no
`WHISPER_MODEL` env var exists in CONTRACT.md's canonical list, so this is a
constructor parameter, not a `Settings` field -- callers (the worker) that
want a different size pass it explicitly. Noted in NOTES.md as a
CONTRACT.md-adjacent choice, not a deviation (CONTRACT.md never specifies a
model-size env var for this).

## No speaker diarization in v1

The `speaker` field in each returned segment is always `None`.
`faster-whisper`/Whisper does not do speaker diarization on its own (that
needs a separate model, e.g. `pyannote.audio`); CONTRACT.md's spec §3.8
return shape marks `speaker` as optional (`speaker?`) precisely because of
this. Wiring diarization is a documented v1 gap, not silently dropped.

## Garage (object storage) fetch

`transcribe_object()` fetches an S3-compatible object from the Garage
bucket configured in `Settings` (`garage_endpoint` /
`garage_access_key_id` / `garage_secret_access_key` / `garage_bucket`)
using `boto3`'s S3 client (Garage speaks the S3 API). `boto3` is imported
lazily inside the function, same pattern as `decision/jev_provider.py`'s
lazy import of its own module and `decision/engine.py`'s lazy import of
`LocalDecisionProvider`/`JevProvider` -- so a deployment that never
transcribes from object storage (local-file-only) doesn't pay for `boto3`
at import time.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from luna.config import Settings, get_settings

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

DEFAULT_MODEL_SIZE = "base"


class TranscriptSegment(TypedDict):
    start: float
    end: float
    text: str
    speaker: str | None


class TranscriptAdapterError(RuntimeError):
    pass


class TranscriptAdapter:
    """Batch faster-whisper transcription. One instance lazily loads (and
    keeps warm) one CTranslate2 Whisper model -- construct one per worker
    process/model-size combination you need, not per job."""

    def __init__(
        self,
        *,
        model_size: str = DEFAULT_MODEL_SIZE,
        device: str = "cpu",
        compute_type: str = "int8",
        download_root: str | None = None,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self._model: WhisperModel | None = None

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root=self.download_root,
            )
        return self._model

    async def transcribe_file(self, path: str | Path) -> list[TranscriptSegment]:
        """Transcribe a local audio file (WAV/PCM, or anything ffmpeg/av can
        decode -- faster-whisper accepts more than just WAV in practice, but
        CONTRACT.md scopes v1 to WAV/PCM so that's the supported contract).
        Runs the blocking faster-whisper call in a worker thread."""
        path = Path(path)
        if not path.exists():
            raise TranscriptAdapterError(f"audio file not found: {path}")
        return await asyncio.to_thread(self._transcribe_sync, path)

    def _transcribe_sync(self, path: Path) -> list[TranscriptSegment]:
        model = self._get_model()
        segments, _info = model.transcribe(str(path), beam_size=5)
        return [
            TranscriptSegment(
                start=float(seg.start),
                end=float(seg.end),
                text=seg.text.strip(),
                speaker=None,
            )
            for seg in segments
        ]

    async def transcribe_object(
        self,
        *,
        key: str,
        settings: Settings | None = None,
    ) -> list[TranscriptSegment]:
        """Fetch `key` from the configured Garage bucket, then transcribe
        it. Raises `TranscriptAdapterError` with a specific, actionable
        message if Garage credentials aren't configured (CONTRACT.md's
        credential-handling policy: fail loudly and specifically, don't
        silently no-op)."""
        settings = settings or get_settings()
        if not (
            settings.garage_endpoint
            and settings.garage_access_key_id
            and settings.garage_secret_access_key
        ):
            raise TranscriptAdapterError(
                "cannot fetch object-storage key "
                f"{key!r}: GARAGE_ENDPOINT/GARAGE_ACCESS_KEY_ID/GARAGE_SECRET_ACCESS_KEY "
                "are not fully configured. Set them, or call transcribe_file() with a "
                "local path instead."
            )

        suffix = Path(key).suffix or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            await asyncio.to_thread(_download_from_garage, settings, key, tmp_path)
            return await self.transcribe_file(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)


def _download_from_garage(settings: Settings, key: str, dest_path: Path) -> None:
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=settings.garage_endpoint,
        aws_access_key_id=settings.garage_access_key_id,
        aws_secret_access_key=settings.garage_secret_access_key,
    )
    try:
        client.download_file(settings.garage_bucket, key, str(dest_path))
    except Exception as exc:  # noqa: BLE001 -- surface as our own error type
        raise TranscriptAdapterError(
            f"failed to download {key!r} from garage bucket {settings.garage_bucket!r}: {exc}"
        ) from exc
