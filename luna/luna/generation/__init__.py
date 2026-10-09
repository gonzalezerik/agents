"""Free-form prose generation -- see `luna.generation.generator.Generation`.

Free-form prose (summaries, draft docs) goes through `Generation.generate()`
instead of the Decision Engine: no schema constraint, never a decision, and
the two are never mixed in one call. This package never imports from `luna.decision` and
never returns anything but a plain `str`.
"""

from __future__ import annotations
