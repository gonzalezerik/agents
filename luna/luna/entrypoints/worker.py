"""`python -m luna.entrypoints.worker` -- runs the JQL poller and the
deadline-reminder scheduler concurrently (CONTRACT.md: "luna-worker"
process). Both loops log and swallow their own per-tick exceptions (see
`workers/poller.py`/`workers/scheduler.py`), so `asyncio.gather` here is only
responsible for keeping both running side by side for the life of the
process -- if one of them ever raises out of its `run_forever()` entirely
(a bug, not a normal tick failure), the process exits non-zero and the
container is expected to restart, which is the correct behavior for an
unexpected crash.
"""

from __future__ import annotations

import asyncio
import logging

from luna.workers import poller, scheduler

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    await asyncio.gather(poller.run_forever(), scheduler.run_forever())


if __name__ == "__main__":
    asyncio.run(main())
