"""The JEV-faithful Decision Engine (spec Part 2, CONTRACT.md "The Decision Engine").

Every capability routes semantic judgment through `DecisionProvider.decide()`
in `luna.decision.engine`. Never call the local LLM directly from a
capability for anything that gates a write -- that's exactly the invariant
`tests/test_jev_conformance.py` item 6 lints for.
"""
