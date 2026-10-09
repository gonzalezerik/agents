"""Periodic scheduler (`luna-worker`) -- drives capability #8 (deadline
reminders) on its own interval. A simple asyncio interval loop is fine for
v1; no heavyweight scheduler library.
`workers/poller.py` already drives #4/#5 every `JIRA_POLL_INTERVAL_SECONDS`
tick as part of its own change-detection loop; this scheduler additionally
drives #8 on a much longer interval of its own, since day-granularity
deadline reminders don't need anywhere near that polling frequency.
It also runs capability #9's read-only risk review on the same tick, so
the latest review is always in `agent_run` for whoever asks (`/risks`
reruns it on demand).
"""

from __future__ import annotations

import asyncio
import logging

from luna.capabilities import deadline_reminders, risk_manager
from luna.db.session import session_scope

logger = logging.getLogger("luna.worker.scheduler")

# Twice a day is plenty of resolution for reminders keyed on whole days.
DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60


async def run_forever(
    *, project_key: str = "C3", interval_seconds: int = DEFAULT_INTERVAL_SECONDS
) -> None:
    while True:
        try:
            async with session_scope() as session:
                await deadline_reminders.check(session, project_key=project_key)
        except Exception:
            logger.exception("scheduler: deadline_reminders check failed")
        try:
            async with session_scope() as session:
                await risk_manager.review(session, project_key=project_key)
        except Exception:
            logger.exception("scheduler: risk_manager review failed")
        await asyncio.sleep(interval_seconds)
