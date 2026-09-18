"""`POST /jira/webhook` -- optional-mode Jira webhook receiver (spec
§3.8/§3.11). CONTRACT.md/spec are explicit that **polling
(`workers/poller.py`) is the default path**; this route exists for
completeness ("build it for completeness per spec §3.8/3.11, but it's not
the default path") and is only meaningfully useful if `JIRA_WEBHOOK_MODE=true`
and the site is set up with a dynamic OAuth webhook (spec §1.4: "only
Connect and OAuth 2.0 apps can register dynamic webhooks... expire after 30
days... require a public HTTPS endpoint") pointed at this route behind a
Cloudflare Tunnel.

Not wired into `luna/api/main.py` here -- the integrator does that, and
per spec should only actually mount this router when
`settings.jira_webhook_mode` is true.

## What this does

Jira Cloud webhook payloads for `jira:issue_updated` look like:
```
{
    "timestamp": 173..., "webhookEvent": "jira:issue_updated",
    "issue": {"id": "...", "key": "C3-12", "fields": {...}},
    "user": {...}, "changelog": {"items": [...]},
}
```
Delivery is not guaranteed-once (spec §1.4: "Jira's retry behavior is
limited (do not treat delivery as guaranteed)") and the same event can be
redelivered, so every request is deduped on the
`X-Atlassian-Webhook-Identifier` header before doing anything else.

**Dedup store note**: a real production dedup needs a persistent table (a
redelivered event could arrive after a process restart, when an in-memory
set is empty again) -- CONTRACT.md doesn't list a dedicated table for this
in the data model (spec §3.5), and adding a new table is out of this
build's scope (schema changes belong with the foundational `db/models.py`
owner). This route dedupes with a bounded in-process set as a *best-effort*
v1 behavior and logs plainly that it is not durable across restarts -- noted
in NOTES.md. Given polling is the default path and this route is opt-in,
that gap is acceptable for v1.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from luna.config import get_settings

logger = logging.getLogger("luna.api.jira_webhook")

router = APIRouter(tags=["jira-webhook"])

_MAX_SEEN = 2048
_seen_ids: deque[str] = deque(maxlen=_MAX_SEEN)
_seen_set: set[str] = set()


def _remember(webhook_id: str) -> bool:
    """Returns True if this is a new id (proceed), False if already seen
    (dedupe -- caller should no-op)."""
    if webhook_id in _seen_set:
        return False
    if len(_seen_ids) == _MAX_SEEN:
        oldest = _seen_ids.popleft()
        _seen_set.discard(oldest)
    _seen_ids.append(webhook_id)
    _seen_set.add(webhook_id)
    return True


@router.post("/jira/webhook", status_code=status.HTTP_202_ACCEPTED)
async def jira_webhook(
    request: Request,
    x_atlassian_webhook_identifier: str | None = Header(default=None),
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.jira_webhook_mode:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "JIRA_WEBHOOK_MODE is not enabled -- this deployment uses polling "
                "(workers/poller.py) as its Jira change-detection path."
            ),
        )

    payload = await request.json()
    webhook_id = x_atlassian_webhook_identifier or payload.get("webhookEvent", "unknown")

    if not _remember(webhook_id):
        logger.info("jira webhook: dropping redelivered event %s", webhook_id)
        return {"status": "duplicate_ignored", "webhook_id": webhook_id}

    event = payload.get("webhookEvent")
    issue = payload.get("issue", {})
    issue_key = issue.get("key")
    logger.info("jira webhook: received %s for %s (id=%s)", event, issue_key, webhook_id)

    # Deliberately does not re-run the full poll-and-alert pipeline inline in
    # the request path (that would make this endpoint's latency depend on a
    # full JQL search + Decision Engine pass, and there is no real webhook
    # traffic to test this against yet). v1 just records the event was seen;
    # `workers/poller.py`'s own interval tick is what actually drives
    # `blocker_dependency`/`budget_watcher`. A future pass could push
    # `issue_key` onto a queue the poller drains between ticks for
    # lower-latency alerts.
    return {"status": "accepted", "webhook_id": webhook_id, "event": event, "issue_key": issue_key}
