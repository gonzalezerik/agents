"""`JiraAdapter` -- the only place in LUNA that speaks Jira Cloud REST v3.

HTTP Basic auth (service-account email + API token)
against `https://{JIRA_SITE}.atlassian.net/rest/api/3/...`. Every *write*
method accepts an `idempotency_key` and no-ops (returns a marker dict,
doesn't raise) if a `Proposal` row already shows that key applied/verified --
checked against Postgres via the `session` argument, never a local cache.

## There is no real Jira site to test against (known, permanent v1 gap)

Atlassian requires interactive human signup for a new Cloud site -- there is
no API for a bot to provision one. Every method here is written to match the
*real*, current (as of 2026) Jira Cloud REST v3 response shapes (see each
method's docstring for the specific endpoint/shape), and is exercised in
`tests/test_adapters_jira.py` against a `respx`-mocked `httpx` transport that
returns those realistic shapes -- but nothing here has ever hit a live Jira
site. The mocked shapes are correct to the best of the current public REST
v3 documentation; if a real site's actual response ever disagrees (a field
renamed, a plan-tier gate, etc.), that is the first thing to check once a
site exists.

**Known 2025 API change baked in on purpose**: Atlassian deprecated
`GET /rest/api/3/search` (the old `startAt`/`total` offset-paginated issue
search) in favor of `POST /rest/api/3/search/jql`, which uses forward-only
`nextPageToken`/`isLast` pagination instead of a total count. `search_jql`
below targets the new endpoint -- if a real site somehow still needs the
legacy one, that's a one-method change, not an interface change.

## How to point this at a real Jira site once one exists

1. Create the Cloud site (interactive signup), create a service-account
   user, and mint an API token for it at
   `https://id.atlassian.com/manage-profile/security/api-tokens`.
2. Set `JIRA_SITE` (the subdomain, e.g. `csunc3` for `csunc3.atlassian.net`),
   `JIRA_EMAIL` (the service account's email), `JIRA_API_TOKEN` in the
   `luna-api`/`luna-worker` deployment's env/secret.
3. Nothing else changes -- `JiraAdapter()` picks these up from
   `luna.config.get_settings()` automatically.
4. **Documented upgrade path** (not implemented; Basic auth is simpler for
   a single-tenant service account in v1): if
   per-user attribution beyond comment-body mentions is ever needed, swap
   Basic auth for OAuth 2.0 (3LO) against
   `https://api.atlassian.com/ex/jira/{cloudId}/rest/api/3/...` -- the method
   signatures here would not need to change, only `__init__`'s auth wiring
   and base URL resolution (a `cloudId` lookup via
   `GET https://api.atlassian.com/oauth/token/accessible-resources` first).
5. **Documented credential-split upgrade**: v1 uses a single `JIRA_EMAIL`/`JIRA_API_TOKEN` service
   account for both reads and writes, noted as a v1 limitation -- if the
   team's Jira plan ever supports multiple API tokens/principals, split into
   `JIRA_*_READONLY` (used by the poller, capabilities #4/#5/#8) and
   `JIRA_*_WRITE` (used only by the confirm-triggered apply path in
   `status_intake.py`).
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.config import Settings, get_settings
from luna.db.models import Proposal, ProposalStatus

_ALREADY_APPLIED_STATUSES = (ProposalStatus.applied, ProposalStatus.verified)


class JiraNotConfiguredError(RuntimeError):
    """Raised at `JiraAdapter()` construction time when JIRA_SITE/JIRA_EMAIL/
    JIRA_API_TOKEN aren't set. This must fail loudly and specifically naming what's missing, not silently
    no-op or crash-loop the whole process. Every capability/worker that
    constructs a JiraAdapter should let this propagate; only the specific
    Jira-dependent feature dies, not the process."""


def _adf_paragraph(text: str) -> dict[str, Any]:
    """Wrap plain text in the Atlassian Document Format `doc` node Jira Cloud
    REST v3 requires for comment/worklog-comment bodies (`POST
    /issue/{key}/comment`'s `body` field is ADF, not plain text, since the
    v3 API's move away from wiki markup)."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


class JiraAdapter:
    """Thin async wrapper over Jira Cloud REST v3. See module docstring for
    auth, the "no real site" testing story, and the upgrade paths."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        settings = settings or get_settings()
        missing = [
            name
            for name, value in (
                ("JIRA_SITE", settings.jira_site),
                ("JIRA_EMAIL", settings.jira_email),
                ("JIRA_API_TOKEN", settings.jira_api_token),
            )
            if not value
        ]
        if missing:
            raise JiraNotConfiguredError(
                f"JiraAdapter requires {', '.join(missing)} to be set -- get a Jira Cloud "
                "site + service-account API token first (see luna/adapters/jira.py's module "
                "docstring for exact steps), then set these in the luna-api/luna-worker "
                "deployment's env/secret. This is a known, permanent gap until a human "
                "creates the site -- there is no API for a bot to provision one."
            )
        self._settings = settings
        self._site = settings.jira_site
        self._client = client or httpx.AsyncClient(
            base_url=f"https://{settings.jira_site}.atlassian.net/rest/api/3",
            auth=httpx.BasicAuth(settings.jira_email, settings.jira_api_token),
            timeout=timeout,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- idempotency ----

    async def _idempotent_noop(
        self, session: AsyncSession | None, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Returns a no-op marker dict if `idempotency_key` already belongs
        to an applied/verified `Proposal`, else `None` (proceed with the real
        write). `session=None` (used by `seed/seed_jira.py`, which isn't part
        of the proposal->confirm->apply lifecycle and does its own
        check-before-create against Jira directly) always proceeds -- there
        is no Proposal row to check against outside that lifecycle."""
        if session is None:
            return None
        result = await session.execute(
            select(Proposal).where(
                Proposal.idempotency_key == idempotency_key,
                Proposal.status.in_(_ALREADY_APPLIED_STATUSES),
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            return None
        return {
            "idempotent_noop": True,
            "idempotency_key": idempotency_key,
            "proposal_id": str(existing.id),
            "proposal_status": existing.status.value,
        }

    # -- reads -------------------------------------------------------------

    async def search_jql(
        self,
        jql: str,
        fields: list[str] | None = None,
        *,
        max_results: int = 50,
        next_page_token: str | None = None,
    ) -> dict[str, Any]:
        """`POST /rest/api/3/search/jql` (the current, non-deprecated search
        endpoint -- see module docstring). Response shape:
        `{"issues": [...], "nextPageToken": str | None, "isLast": bool}`.
        Paginate by passing the previous response's `nextPageToken` back in
        until `isLast` is true."""
        body: dict[str, Any] = {"jql": jql, "maxResults": max_results}
        if fields is not None:
            body["fields"] = fields
        if next_page_token is not None:
            body["nextPageToken"] = next_page_token
        resp = await self._client.post("/search/jql", json=body)
        resp.raise_for_status()
        return resp.json()

    async def get_issue(self, key: str, fields: list[str] | None = None) -> dict[str, Any]:
        """`GET /rest/api/3/issue/{key}`. Response:
        `{"id": str, "key": str, "fields": {...}}`."""
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        resp = await self._client.get(f"/issue/{key}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def list_components(self, project_key: str) -> list[dict[str, Any]]:
        """`GET /rest/api/3/project/{projectIdOrKey}/components`. Response:
        a bare list of `{"id", "name", "description", ...}` objects (not
        wrapped in a paging envelope, unlike most other v3 list endpoints)."""
        resp = await self._client.get(f"/project/{project_key}/components")
        resp.raise_for_status()
        return resp.json()

    async def list_versions(self, project_key: str) -> list[dict[str, Any]]:
        """`GET /rest/api/3/project/{projectIdOrKey}/versions`. Response:
        a bare list of `{"id", "name", "released", "releaseDate", ...}`."""
        resp = await self._client.get(f"/project/{project_key}/versions")
        resp.raise_for_status()
        return resp.json()

    # -- admin/seed-only methods (beyond the core adapter interface) --
    #
    # `seed/seed_jira.py` needs a few more Jira Cloud admin resource types
    # (custom fields, issue types, global statuses) that capabilities never
    # use. Kept here rather than reaching
    # into `self._client` from seed_jira.py directly, so this stays the one
    # place in LUNA that speaks Jira REST. These are not part of the
    # write-proposal/idempotency_key lifecycle (seed isn't Proposal-driven --
    # it does its own check-before-create), so no `idempotency_key`/`session`
    # params here.

    async def list_fields(self) -> list[dict[str, Any]]:
        """`GET /rest/api/3/field`. Response: a bare list of every field
        (system + custom) with `{"id", "name", "custom", "schema", ...}`."""
        resp = await self._client.get("/field")
        resp.raise_for_status()
        return resp.json()

    async def create_field(
        self, *, name: str, field_type: str, description: str = ""
    ) -> dict[str, Any]:
        """`POST /rest/api/3/field`, body
        `{"name", "description", "type": "com.atlassian.jira.plugin.system.customfieldtypes:<...>"}`.
        `field_type` is that fully-qualified custom-field-type key (e.g.
        `"com.atlassian.jira.plugin.system.customfieldtypes:float"` for a
        number field, `"...:select"` for a single-select). Response:
        `{"id": "customfield_NNNNN", "name", ...}`."""
        resp = await self._client.post(
            "/field", json={"name": name, "description": description, "type": field_type}
        )
        resp.raise_for_status()
        return resp.json()

    async def create_component(
        self, project_key: str, *, name: str, description: str = ""
    ) -> dict[str, Any]:
        """`POST /rest/api/3/component`, body `{"project", "name",
        "description"}`. Response: `{"id", "name", "description", ...}`."""
        resp = await self._client.post(
            "/component", json={"project": project_key, "name": name, "description": description}
        )
        resp.raise_for_status()
        return resp.json()

    async def create_version(
        self,
        project_key: str,
        *,
        name: str,
        release_date: str | None = None,
        released: bool = False,
    ) -> dict[str, Any]:
        """`POST /rest/api/3/version`, body `{"project", "name",
        "releaseDate", "released"}`. Response: `{"id", "name", ...}`."""
        body: dict[str, Any] = {"project": project_key, "name": name, "released": released}
        if release_date is not None:
            body["releaseDate"] = release_date
        resp = await self._client.post("/version", json=body)
        resp.raise_for_status()
        return resp.json()

    async def list_issue_types(self) -> list[dict[str, Any]]:
        """`GET /rest/api/3/issuetype`. Response: a bare list of
        `{"id", "name", "subtask": bool, ...}`. Note (documented honestly,
        untested against a real site): issue-type management differs
        substantially between company-managed and team-managed projects --
        this classic global endpoint applies to company-managed (`"classic"`)
        projects; a team-managed project manages its own issue-type set
        through a different, project-scoped mechanism the public REST API
        exposes less of. `seed/seed_jira.py` assumes company-managed."""
        resp = await self._client.get("/issuetype")
        resp.raise_for_status()
        return resp.json()

    async def create_issue_type(
        self, *, name: str, description: str = "", subtask: bool = False
    ) -> dict[str, Any]:
        """`POST /rest/api/3/issuetype`, body `{"name", "description",
        "type": "subtask"|"standard"}`. See `list_issue_types`'s
        company-managed-vs-team-managed caveat."""
        resp = await self._client.post(
            "/issuetype",
            json={
                "name": name,
                "description": description,
                "type": "subtask" if subtask else "standard",
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def list_statuses(self) -> list[dict[str, Any]]:
        """`GET /rest/api/3/status`. Response: a bare list of every global
        status with `{"id", "name", "statusCategory": {...}, ...}`."""
        resp = await self._client.get("/status")
        resp.raise_for_status()
        return resp.json()

    async def create_global_status(
        self, *, name: str, status_category: str = "TODO", description: str = ""
    ) -> dict[str, Any]:
        """`POST /rest/api/3/statuses` (the bulk-create endpoint -- there is
        no single-status create), body `{"scope": {"type": "GLOBAL"},
        "statuses": [{"name", "statusCategory", "description"}]}`.
        `status_category` is one of `"TODO"`, `"IN_PROGRESS"`, `"DONE"`.
        Response: a list with one created status object.

        **Documented gap**: this creates the *status resource* itself.
        Actually inserting it into an existing workflow's transition graph
        (so issues can actually be moved to `Blocked`) is a separate,
        substantially more involved operation (editing workflow transitions
        via the Workflow API, or manually in the Jira UI) that depends on
        whether the project's workflow is even editable via the public API
        at the site's plan tier -- not implemented here, called out
        explicitly since silently pretending this one call wires up the
        whole `Blocked` status in the board would be dishonest."""
        resp = await self._client.post(
            "/statuses",
            json={
                "scope": {"type": "GLOBAL"},
                "statuses": [
                    {"name": name, "statusCategory": status_category, "description": description}
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()

    # -- writes (idempotency_key required on every one) --------------------

    async def create_issue(
        self,
        *,
        fields: dict[str, Any],
        idempotency_key: str,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """`POST /rest/api/3/issue`, body `{"fields": {...}}`. Real success
        response: `{"id": str, "key": str, "self": str}`."""
        noop = await self._idempotent_noop(session, idempotency_key)
        if noop is not None:
            return noop
        resp = await self._client.post("/issue", json={"fields": fields})
        resp.raise_for_status()
        return resp.json()

    async def transition_issue(
        self,
        key: str,
        transition_id: str,
        *,
        idempotency_key: str,
        fields: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """`POST /rest/api/3/issue/{key}/transitions`, body
        `{"transition": {"id": transition_id}, "fields": {...}}`. Real Jira
        returns `204 No Content` on success -- there is no JSON body, so we
        synthesize `{"status": 204, "key": key, "transition_id": ...}` for a
        uniform return shape."""
        noop = await self._idempotent_noop(session, idempotency_key)
        if noop is not None:
            return noop
        body: dict[str, Any] = {"transition": {"id": transition_id}}
        if fields:
            body["fields"] = fields
        resp = await self._client.post(f"/issue/{key}/transitions", json=body)
        resp.raise_for_status()
        return {"status": resp.status_code, "key": key, "transition_id": transition_id}

    async def add_comment(
        self,
        key: str,
        body: str,
        *,
        idempotency_key: str,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """`POST /rest/api/3/issue/{key}/comment`, body `{"body": <ADF doc>}`
        (v3 requires Atlassian Document Format, not plain text/wiki markup).
        Real response: `{"id", "body", "author", "created", "updated", ...}`."""
        noop = await self._idempotent_noop(session, idempotency_key)
        if noop is not None:
            return noop
        resp = await self._client.post(
            f"/issue/{key}/comment", json={"body": _adf_paragraph(body)}
        )
        resp.raise_for_status()
        return resp.json()

    async def update_fields(
        self,
        key: str,
        fields: dict[str, Any],
        *,
        idempotency_key: str,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """`PUT /rest/api/3/issue/{key}`, body `{"fields": {...}}`. Real Jira
        returns `204 No Content` on success."""
        noop = await self._idempotent_noop(session, idempotency_key)
        if noop is not None:
            return noop
        resp = await self._client.put(f"/issue/{key}", json={"fields": fields})
        resp.raise_for_status()
        return {"status": resp.status_code, "key": key, "fields": fields}

    async def add_worklog(
        self,
        key: str,
        *,
        idempotency_key: str,
        time_spent_seconds: int | None = None,
        time_spent: str | None = None,
        comment: str | None = None,
        started: str | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """`POST /rest/api/3/issue/{key}/worklog`. Body carries either
        `timeSpentSeconds` (int) or `timeSpent` (Jira duration string, e.g.
        `"3h 30m"`) -- pass exactly one. Real response (`201`): worklog
        object with `id`, `timeSpentSeconds`, `started`, `author`, ..."""
        if (time_spent_seconds is None) == (time_spent is None):
            raise ValueError("add_worklog needs exactly one of time_spent_seconds/time_spent")
        noop = await self._idempotent_noop(session, idempotency_key)
        if noop is not None:
            return noop
        body: dict[str, Any] = {}
        if time_spent_seconds is not None:
            body["timeSpentSeconds"] = time_spent_seconds
        else:
            body["timeSpent"] = time_spent
        if comment is not None:
            body["comment"] = _adf_paragraph(comment)
        if started is not None:
            body["started"] = started
        resp = await self._client.post(f"/issue/{key}/worklog", json=body)
        resp.raise_for_status()
        return resp.json()
