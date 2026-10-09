# agents

A collection of task-specific agents. Each one lives in its own folder with
its own README, dependencies and tests.

| Agent | What it does | Status |
|---|---|---|
| [`luna/`](luna/) | Local-first agentic layer over Jira, Discord and Slack for a student lunar rover team: status intake, standups, meeting action items, blocker/budget alerts, Q&A with citations, design-review drafts, deadline reminders, and a risk manager. | Work in progress, not deployed |

Shared rule across these agents: the model only answers typed questions
(choose, score, yes/no) with probabilities; code owns the math, control flow
and side effects, and anything that writes to another system goes through a
human-confirmed proposal.
