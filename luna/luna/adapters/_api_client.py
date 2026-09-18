"""Shared internal helper: the httpx client both `discord_adapter.py` and
`slack_adapter.py` use to call **their own** `luna-api` service.

CONTRACT.md: "the bot calls its own API, not the other way around, to keep
one source of truth for proposal state." So every write this build makes
goes through here: `POST /ingest/discord` / `POST /ingest/slack` (this
build's own `luna/api/routes/ingest.py`) and `POST
/proposals/{id}/confirm|cancel|edit` (another builder's route -- may not
exist yet in this worktree; calls to it will 404 until it lands, which is
expected and handled the same as any other transport/HTTP error, see
`LunaAPIError`).

Not one of CONTRACT.md's enumerated files -- a private submodule (leading
underscore) under the already-contracted `luna/adapters/` package, holding
~30 lines of httpx boilerplate that both adapters would otherwise duplicate.

Auth: `INTERNAL_SERVICE_TOKEN` bearer, same shared secret every other route
in this codebase checks (`api/deps.py`). Base URL: `LUNA_API_BASE` (added to
`luna/config.py` by this build, see its docstring there).
"""

from __future__ import annotations

from typing import Any

import httpx

from luna.config import get_settings


class LunaAPIError(RuntimeError):
    """A call from a bot process to its own luna-api failed (non-2xx or a
    transport-level error, e.g. luna-api unreachable). Callers should catch
    this, log it, and tell the user something went wrong rather than let it
    crash the bot process's event loop -- a single failed API call is never
    fatal to `luna-discord`/`luna-slack` the way a missing bot token is."""


class LunaAPIClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url if base_url is not None else settings.luna_api_base).rstrip("/")
        self.token = token if token is not None else settings.internal_service_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def _post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
            try:
                resp = await client.post(path, json=json, headers=self._headers())
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise LunaAPIError(f"luna-api call to {path} failed: {exc}") from exc
        return resp.json()

    async def ingest_discord(self, event: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/ingest/discord", event)

    async def ingest_slack(self, event: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/ingest/slack", event)

    async def confirm_proposal(self, proposal_id: str) -> dict[str, Any]:
        return await self._post(f"/proposals/{proposal_id}/confirm", {})

    async def cancel_proposal(self, proposal_id: str) -> dict[str, Any]:
        return await self._post(f"/proposals/{proposal_id}/cancel", {})

    async def edit_proposal(self, proposal_id: str, edits: dict[str, Any]) -> dict[str, Any]:
        return await self._post(f"/proposals/{proposal_id}/edit", edits)
