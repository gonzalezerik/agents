"""`python -m luna.entrypoints.discord_bot` -- the `luna-discord` process.

Wires `luna/adapters/discord_adapter.py`'s `Bot` instance and slash commands.
A missing/placeholder `DISCORD_BOT_TOKEN` is fatal to this whole process --
nothing it does is useful without a real bot session, same "crash-loop with
a clear, specific log message" pattern the abandoned Cairn project's
`cairn-bot` used (this repo's owner explicitly asked for it repeated here).
This is deliberately different from a feature-specific credential like
`GARAGE_*` (see `discord_adapter.py`'s `/record` handling), which fails
loudly only for the one feature that needs it and leaves the rest of the bot
running.
"""

from __future__ import annotations

import logging
import sys

from luna.adapters._api_client import LunaAPIClient
from luna.adapters.discord_adapter import build_bot, register_commands
from luna.config import get_settings

logger = logging.getLogger("luna.entrypoints.discord_bot")

_MISSING_TOKEN_MESSAGE = (
    "DISCORD_BOT_TOKEN is not set (or is a placeholder). luna-discord cannot start "
    "without a real Discord bot token -- refusing to run, this process will "
    "crash-loop until a real token is provided.\n"
    "To get one: Discord Developer Portal (https://discord.com/developers/applications) "
    "-> New Application -> Bot -> Reset Token, then set DISCORD_BOT_TOKEN in the "
    "luna-discord deployment's env/secret. When inviting the bot to the server, grant "
    "it the 'bot' and 'applications.commands' OAuth2 scopes so the slash commands "
    "(/status /ask /standup /record /blockers /budget) register."
)


def _require_token() -> str:
    settings = get_settings()
    token = settings.discord_bot_token.strip()
    if not token:
        logger.critical(_MISSING_TOKEN_MESSAGE)
        sys.exit(1)
    return token


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = _require_token()

    bot = build_bot()
    api_client = LunaAPIClient()
    register_commands(bot, api_client)

    logger.info("luna-discord starting -- connecting to the Discord gateway")
    bot.run(token)


if __name__ == "__main__":
    main()
