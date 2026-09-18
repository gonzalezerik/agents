"""Free-form prose generation -- see `luna.generation.generator.Generation`.

CONTRACT.md: "Free-form prose (summaries, draft docs) goes through
`Generation.generate()` instead [of the Decision Engine], which has no
schema constraint and never produces a decision -- the two must not be
mixed in one call." This package never imports from `luna.decision` and
never returns anything but a plain `str`.
"""

from __future__ import annotations
