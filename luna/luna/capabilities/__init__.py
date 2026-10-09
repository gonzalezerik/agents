"""Capability modules. Importing a capability module registers
its `control_loop` nodes as a side effect (`register_node()` calls at module
top level) -- see each module's docstring for which `RunStatus` stages it
implements.

Importing this package imports every capability submodule below, which is
what actually makes registration happen -- nothing else in the codebase does
this. This was a real integration gap found while wiring the Jira, chat, and
knowledge layers together: `luna/api/routes/ingest.py` and
`luna/api/routes/proposals.py` both call `control_loop.run()`/`resume()` by
capability *name* (a string), with no direct import of the capability
modules themselves, and `control_loop.py`'s node registry silently no-ops
any `(capability, node)` pair nothing registered -- so without this,
`luna-api` and `luna-worker` would serve every request as a silent no-op in
production, never actually calling Jira/the Decision Engine/anything. Import
`luna.capabilities` (this package) once, early, in every process entrypoint
that drives a control-loop run -- `luna/api/main.py`'s `create_app()` and
`luna/entrypoints/worker.py` both do this now.
"""

from __future__ import annotations

from . import (  # noqa: F401 - imported for registration side effects
    blocker_dependency,
    budget_watcher,
    deadline_reminders,
    design_review,
    meeting_action_items,
    rag_qna,
    risk_manager,
    standup,
    status_intake,
)

__all__ = [
    "blocker_dependency",
    "budget_watcher",
    "deadline_reminders",
    "design_review",
    "meeting_action_items",
    "rag_qna",
    "risk_manager",
    "standup",
    "status_intake",
]
