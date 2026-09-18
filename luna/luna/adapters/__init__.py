"""Integration adapters (CONTRACT.md `luna/adapters/`).

`jira.py` (JiraAdapter), `discord_adapter.py` + `slack_adapter.py` (chat, plus
the shared internal `_api_client.py` helper they both use), and
`transcript.py` (TranscriptAdapter, faster-whisper).
"""

from __future__ import annotations
