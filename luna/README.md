# LUNA

> **Work in progress — not deployed.** LUNA is not running anywhere the team
> can use yet. There is no Jira Cloud site for it to talk to, and the Discord
> and Slack bots have no tokens. Everything below is written and tested
> against mocks and a local Postgres, not against real Jira, Discord or Slack.
> Don't rely on it for team decisions until this notice is gone.

LUNA is a local-first agentic layer over Jira, Discord and Slack for the CSUN
C3 lunar rover team. Jira stays the system of record. Team members talk to
LUNA in chat, and LUNA proposes Jira changes that a human confirms before
anything is written.

Known gaps are documented in the module docstrings where they live (for
example, recorded voice is uploaded but not yet transcribed -- see
`luna/adapters/discord_adapter.py`).

## How it decides things

The language model never acts on its own. Every judgment is a typed question
(pick one option, rate on a scale, or yes/no) answered with a probability,
through the Decision Engine (`luna/decision/`). Code does all the arithmetic
and control flow. Any Jira write goes through proposal → human confirm →
apply → verify. Models run locally through an OpenAI-compatible endpoint
(llama.cpp); no cloud model is on the critical path.

## Capabilities

| # | Capability | Chat command | Writes to Jira? |
|---|---|---|---|
| 1 | Status intake from chat | `/status` | Yes, after confirm |
| 2 | Standup / weekly summaries | `/standup` | No (may propose action items) |
| 3 | Meeting transcript → action items (local Whisper) | `/record` | Yes, after confirm |
| 4 | Blocker / stale / cross-subteam dependency alerts | `/blockers` | No |
| 5 | Budget and margin watcher (mass, power, cost, data rate) | `/budget` | No |
| 6 | Q&A over Jira and docs, with citations | `/ask` | No |
| 7 | Design-review package drafts (PDR/CDR-style) | — | No (git PR only) |
| 8 | Milestone deadline reminders | — | No |
| 9 | Risk manager: register review, milestone exposure, notes → risk proposals | `/risks` | Yes, after confirm |

## Running the tests

Python 3.11+. Tests need no live Jira, Discord, Slack or LLM. Tests that use
the database skip if Postgres isn't reachable, and tests marked `llm` skip if
`LLM_BASE_URL` isn't reachable.

```sh
pip install -e '.[dev]'
export DATABASE_URL=postgresql+asyncpg://luna@127.0.0.1:55432/luna   # Postgres with pgvector
pytest
```

The LLM endpoint is configured with `LLM_BASE_URL`, `LLM_MODEL` and
`LLM_API_KEY`. Secrets are never committed. See `luna/config.py` for every
setting.

## Where it runs

Container images build from `deploy/Dockerfile.*` (build context: this
`luna/` folder). Kubernetes manifests are not part of this repository.
