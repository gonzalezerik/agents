"""Capability modules (spec §3.3). Importing a capability module registers
its `control_loop` nodes as a side effect (`register_node()` calls at module
top level) -- see each module's docstring for which `RunStatus` stages it
implements. `luna/entrypoints/worker.py` and `luna/api/routes/proposals.py`
import the write-capable/alerting capabilities so their nodes are registered
before any run is driven.
"""

from __future__ import annotations
