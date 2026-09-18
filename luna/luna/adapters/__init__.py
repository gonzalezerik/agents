"""Integration adapters (CONTRACT.md `luna/adapters/`).

This worktree's scope covers only the chat layer: `discord_adapter.py`,
`slack_adapter.py`, and the shared internal `_api_client.py` helper they both
use. `jira.py` and `transcript.py` belong to other builders and are not
present here yet.
"""

from __future__ import annotations
