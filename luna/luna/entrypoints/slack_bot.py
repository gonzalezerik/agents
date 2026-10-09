"""`python -m luna.entrypoints.slack_bot` -- the `luna-slack` process.

Wires `luna/adapters/slack_adapter.py`'s Bolt `AsyncApp` behind Socket Mode
(`AsyncSocketModeHandler`, an outbound WebSocket -- no public endpoint or
Ingress route, see `slack_adapter.py`'s docstring). Missing/placeholder
`SLACK_BOT_TOKEN` or `SLACK_APP_TOKEN` is fatal to this whole process, same
crash-loop-with-clear-message pattern as `discord_bot.py`: nothing this process does is useful without
both tokens.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from luna.adapters._api_client import LunaAPIClient
from luna.adapters.slack_adapter import build_app, register_handlers
from luna.config import get_settings

logger = logging.getLogger("luna.entrypoints.slack_bot")

_MISSING_TOKENS_MESSAGE = (
    "{missing} not set (or a placeholder). luna-slack cannot start Socket Mode "
    "without both a bot token and an app-level token -- refusing to run, this "
    "process will crash-loop until real tokens are provided.\n"
    "To get them: api.slack.com/apps -> create (or open) the app -> Socket Mode "
    "-> enable it -> generate an App-Level Token with the 'connections:write' "
    "scope (this is SLACK_APP_TOKEN, starts with 'xapp-') -> OAuth & Permissions "
    "-> install the app to the workspace to get a Bot User OAuth Token (this is "
    "SLACK_BOT_TOKEN, starts with 'xoxb-'). Set both in the luna-slack deployment's "
    "env/secret."
)


def _require_tokens() -> None:
    settings = get_settings()
    missing = []
    if not settings.slack_bot_token.strip():
        missing.append("SLACK_BOT_TOKEN")
    if not settings.slack_app_token.strip():
        missing.append("SLACK_APP_TOKEN")
    if missing:
        logger.critical(_MISSING_TOKENS_MESSAGE.format(missing=" and ".join(missing)))
        sys.exit(1)


async def _run() -> None:
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    settings = get_settings()
    app = build_app()
    api_client = LunaAPIClient()
    register_handlers(app, api_client)

    logger.info("luna-slack starting -- connecting via Socket Mode")
    handler = AsyncSocketModeHandler(app, app_token=settings.slack_app_token)
    await handler.start_async()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    _require_tokens()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
