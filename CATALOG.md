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
| [`incident-agent/`](incident-agent/) | When a Kubernetes alert fires: gathers pod state and events, asks a model for root cause and a fix, and offers one-click approval of the only allowed action (restart a pod); escalates to a human otherwise. | Deployed in my ops dashboard; model endpoint down, so every run escalates (correctly). |
| [`graph-runtime/`](graph-runtime/) | Typed node graphs with Postgres checkpoints and human-approval interrupts; three graphs (incident investigation, a11y fix, generate-evaluate), MCP tool servers, an eval runner. | Running and healthy, but only ever used for manual test runs; its model backend is gone. |
| [`cephlapod/`](cephlapod/) | Orchestration harness for coding agents on a local model pool: Anthropic↔OpenAI shim with tool-call repair and a router model, GPU-host agent that starts and stops models, reconciler with preemption. 93 characterization tests. | Not running since the GPU-server rebuild. |
| [`leviathan/`](leviathan/) | News-intelligence dashboard: clusters RSS stories with a small model, rates supply-chain risk with a larger one, two-role synthesis on a 3D globe. | Deployed; both model endpoints down. |

## Not published yet

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
