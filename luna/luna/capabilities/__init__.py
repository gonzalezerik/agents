"""Agent capabilities (CONTRACT.md `luna/capabilities/`).

This build's scope is `standup.py` (#2), `meeting_action_items.py` (#3),
`rag_qna.py` (#6), and `design_review.py` (#7), plus the private
`_util.py` helper they share. `status_intake.py` (#1),
`blocker_dependency.py` (#4), `budget_watcher.py` (#5), and
`deadline_reminders.py` (#8) are other builders' files and intentionally do
not exist in this worktree -- see NOTES.md.
"""

from __future__ import annotations
