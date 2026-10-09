# Agent catalog

Everything agent-shaped I've built so far, what state it's in, and what's
left before it could live in this repo. Surveyed 2026-10-08. "Running" means
the service is deployed; it does not mean the agent works end to end — see
the notes.

Most of these depend on self-hosted model servers. After a GPU server
rebuild in late September 2026, only one of its model endpoints is back, so
several agents below are deployed but can't reach a model.

## In this repo

| Agent | What it does | State |
|---|---|---|
| [`luna/`](luna/) | Agentic layer over Jira, Discord and Slack for a student lunar rover team. Typed decisions only (choose / score / yes-no), human-confirmed writes, risk manager. | Code and tests complete for v1; not deployed (no Jira site or bot tokens yet). Recorded voice is uploaded but never transcribed. |
| [`a11y-agent/`](a11y-agent/) | Visitors report accessibility barriers on my site; an agent triages each report against a WCAG 2.2 criterion, proposes a patch, and a human approves the deploy. | Widget live. Agent deployed but broken: its model endpoint is down, and a failed model call currently dismisses the report. See its README. |

## Not published yet

### Ops incident-investigation agent
Part of my private ops dashboard. Collects context for an alert (pod status and
recent Kubernetes events), asks a model for root cause, a proposed fix and a confidence,
records everything in an audit log, and offers one-click apply or a manual
takeover. Has eval cases.
- **State:** deployed with the dashboard; its model endpoint is down, so
  diagnoses currently fail.
- **Left:** extract it with history the same way as `a11y-agent/` (it
  shares the audit-log and LLM modules); move its free-text answer parsing
  to schema-constrained output; decide whether it runs on the graph runtime
  below.

### Graph runtime with human-approval interrupts
A small Python engine that runs typed node graphs with checkpointing and
pauses for human approval before risky steps. Ships one graph (incident
investigation); the eval files target it.
- **State:** code exists, but nothing deploys or runs it right now.
- **Left:** decide whether it becomes the shared runtime for the ops agents
  (and how it relates to LUNA's control loop); add tests; extract.

### LLM orchestration harness
The routing layer that let coding agents talk to a pool of local models:
an Anthropic-Messages-to-OpenAI translation shim with a model router and
tool-call repair, a model-pool manager that starts and stops models to fit
GPU memory (with preemption), and a dashboard reconciler. 34 TypeScript and
59 Python characterization tests already exist.
- **State:** not running since the GPU server rebuild. The source survives
  only in a pre-rebuild snapshot and a server backup directory; part of it
  was never in version control.
- **Left:** get every piece into git first. Then the planned extraction:
  stages B–H after the completed stage A (characterization tests), fixing
  the three bugs stage A found (dead `restore` action, user text dropped
  when a message mixes text and tool results, a VRAM-gap check that can
  never trigger).

### Small-business assistant + sandboxed coding agent
For a booking app I built for a small beauty business. An admin assistant
with 21 tools, streaming, memory, and a confirm step for every write action,
plus a red-team prompt-injection script and a tool-calling eval. For changes
the tools can't make, it hands off to a sandboxed coding agent that runs as
a one-off Kubernetes Job: clone, edit through a file-tool loop, gate on
`tsc`, `eslint` and `next build` (with up to two repair attempts), deploy a
preview, and go live only on explicit approval.
- **State:** the assistant is running, and its model endpoint answers
  (only checked that it responds; a full chat was not run).
- **Left:** strip client-identifying details and the architecture guide it
  was built from; the coding agent needs its own README section; screenshot
  review of previews is not built.

### Public booking assistant
The customer-facing chat on the same booking app: unauthenticated, so its
safety comes from what it structurally can't do. It has three tools (list
services, check availability, submit a booking), a hard cap on tool-call
iterations and on turns per conversation, and bot protection.
- **State:** running inside the booking app.
- **Left:** extract from the client app; good small example of a
  capability-restricted public agent.

### Landscaping-business assistant
Owner and crew chat for a second small-business app, including voice notes
transcribed and turned into proposed actions.
- **State:** deployed. Its model and speech endpoints point at the GPU
  server; whether they currently work was not verified.
- **Left:** check the endpoints; separate it from the client app.

### LUNA's own models (LUNA-Predict / -Decide / -Chat)
A training platform for small calibrated models for LUNA: a deterministic
project simulator for ground-truth labels, LLM-enriched text, features,
baselines, leakage checks, ONNX export. A smoke run completed.
- **State:** two commits; integration with LUNA's Decision Engine has not
  started.
- **Left:** remove the build spec references, finish a real training run,
  and wire LUNA-Decide in as a `DecisionProvider`. Would live next to
  `luna/`.

### News-clustering engine
Pulls RSS feeds by region, uses one small model to group headlines into
topics and a larger one to synthesize them.
- **State:** deployed, but both model endpoints are down.
- **Left:** point it at the current model server; decide if it's an agent
  or just an LLM pipeline (no tools, no decisions).

### Rover onboard assistant
On the rover's Jetson: a local model router with several small models and a
terminal coding agent configured against it, for the team to use on the
robot.
- **State:** running on the robot (setup scripts, not an app).
- **Left:** it's configuration more than code; could be documented here as
  a recipe.

### Superseded
- **Cairn's agent service** — six agents (standup summarizer, action-item
  extractor, blocker detector, budget watcher, design-review assembler, Q&A)
  for the rover team's earlier project-management app. Scaled to zero;
  LUNA replaced it. Not worth publishing separately.
- **Local-model delegation MCP tool** — let a coding agent delegate prompts to
  specific local models. It names models that no longer exist after the
  rebuild; small enough to rewrite rather than extract.
