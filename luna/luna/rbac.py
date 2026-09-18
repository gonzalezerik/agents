"""Capability -> required Jira/roster scope checks (CONTRACT.md).

CONTRACT.md explicitly allows this to be "minimal/stubbed if the concrete
rules aren't yet clear from spec, but the interface must exist for other
modules to import." The spec (§3.2 roster, §3.6 "scoped credentials") talks
about read-only vs write-capable Jira principals and per-capability write
policy (R vs W, spec §3.3's numbered capability list), but does not define a
concrete permission matrix beyond "every Jira write = proposal -> confirm ->
apply -> verify, no exceptions" (which guardrails.py already enforces
unconditionally, independent of any role check here).

This module gives capabilities a single, stable place to ask "is this actor
allowed to do X" without hardcoding Jira-role assumptions into each
capability module. The current implementation is intentionally
permissive/stubbed (see NOTES.md) -- it exists so `capabilities/*.py` can
import and call it now, and a real policy (backed by `roster.subteams` /
`roster.licensed_bool`, or Jira's own permission scheme via 3LO) can be
dropped in later without changing every call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Scope(StrEnum):
    """Coarse capability scopes. Kept small and additive -- extend as real
    per-capability rules are defined, don't repurpose an existing member's
    meaning."""

    JIRA_READ = "jira:read"
    JIRA_WRITE = "jira:write"
    DOCS_WRITE = "docs:write"  # capability #7's git-commit-only path
    ADMIN = "admin"


# capability name (as used in agent_run.capability / luna/capabilities/*.py
# module names) -> the scopes it needs. Left intentionally small: only the
# write-capable capabilities from spec §3.3 are listed (#1, #3, #7); every
# other capability (#2, #4, #5, #6, #8) is read-only and only needs
# JIRA_READ, which every capability is granted by default below.
CAPABILITY_SCOPES: dict[str, frozenset[Scope]] = {
    "status_intake": frozenset({Scope.JIRA_READ, Scope.JIRA_WRITE}),
    "meeting_action_items": frozenset({Scope.JIRA_READ, Scope.JIRA_WRITE}),
    "design_review": frozenset({Scope.JIRA_READ, Scope.DOCS_WRITE}),
}

_DEFAULT_SCOPES = frozenset({Scope.JIRA_READ})


@dataclass(frozen=True, slots=True)
class Actor:
    """Minimal actor identity for an RBAC check. `user_id` should be a
    `roster.user_id` when known; capabilities acting on behalf of the
    service account itself (e.g. the poller) pass `user_id=None` and
    `is_service=True`."""

    user_id: str | None
    is_service: bool = False
    is_admin: bool = False


def required_scopes(capability: str) -> frozenset[Scope]:
    """What scopes a capability needs to run at all. Does not vary by
    actor -- this answers "what can this capability ever do", not "can this
    specific user invoke it" (see `can_perform` for that)."""
    return CAPABILITY_SCOPES.get(capability, _DEFAULT_SCOPES)


def can_perform(actor: Actor, capability: str, scope: Scope) -> bool:
    """Stubbed policy: admins and the service account can do anything a
    capability is scoped for; every other actor can do anything the
    capability is scoped for too (v1 has no per-user scope restriction below
    the capability level -- see module docstring). The one real check this
    function performs is that `scope` must actually be one of the
    capability's `required_scopes()`, so a bug that asks "can this actor
    JIRA_WRITE" against a read-only capability fails closed rather than
    silently succeeding.
    """
    if scope not in required_scopes(capability):
        return False
    if actor.is_admin or actor.is_service:
        return True
    # v1: no further per-user restriction. Tighten here (e.g. checking
    # roster.licensed_bool / roster.subteams against the target component)
    # once the concrete policy is defined -- CONTRACT.md explicitly allows
    # shipping this stubbed for now.
    return True
