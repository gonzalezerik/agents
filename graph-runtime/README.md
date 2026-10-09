# graph-runtime (mc-graph)

> **Work in progress.** Running on my ops host and healthy, but it has only
> ever executed manual test runs (September 2026), one of which is still
> stuck in `running`, and its model calls go to a pool manager that no
> longer exists after a GPU-server rebuild. Extracted with commit history
> from a private ops dashboard repo; the last commit syncs it with the copy
> that is actually deployed, which had moved past git.

A small Python engine for agent workflows written as typed node graphs:
state schema, nodes, edges, checkpoints after every node, and human-approval
interrupts that pause a run until someone decides.

## What's here

- `mc-graph/engine.py` — runs a graph: node types `tool`, `llm`, `router`,
  `human` (an interrupt that waits for an approval decision) and
  `evaluator`; checkpoints state to Postgres after each node; records spans
  with token counts.
- `mc-graph/main.py` — FastAPI: start and list runs, read checkpoints and
  spans, list and decide approvals, list graphs and their eval history,
  health.
- `mc-graph/graphs/` — three graphs:
  - `incident_investigation` — gather Kubernetes context → model
    investigation and proposal → route → human approval → restart pod →
    evaluate the result;
  - `a11y_fix` — the accessibility triage loop from `../a11y-agent/` as a
    graph;
  - `generator_evaluator` — a reusable generate → evaluate → pass / retry /
    fail subgraph (used for media generation).
- `mc-graph/tools.py` — Kubernetes read/restart/rollout, Forgejo
  fetch/commit/build-trigger, model calls, reporter notification.
- `mc-graph/mcp/` — the same tools exposed as MCP servers (JSON-RPC over
  HTTP) for Kubernetes and Forgejo.
- `mc-graph/eval_runner.py` + `evals/` — runs a graph's eval tasks and
  records pass/fail per contract.

## Known gaps

- **No model backend.** `llm` nodes call the model-pool manager from
  `../cephlapod/`, which isn't running since the GPU-server rebuild; calls
  return an error string instead of failing the node loudly.
- **No tests** for the engine itself; the eval tasks test graphs, not the
  runtime.
- **Overlaps with other loops.** `incident_investigation` duplicates
  `../incident-agent/`, `a11y_fix` duplicates `../a11y-agent/`, and LUNA has
  its own checkpointed control loop. Picking one runtime is the open
  decision.
- **Credentials.** Defaults for the database and Forgejo were placeholders
  in this extraction; real values must come from the environment.

## Configuration

`DATABASE_URL`, `MC_AGENT_URL`, `MC_AGENT_TOKEN`, `KUBECONFIG`,
`FORGEJO_URL`, `FORGEJO_USER`, `FORGEJO_TOKEN`/`FORGEJO_PASSWORD`,
`FORGEJO_REPO`. `start.sh` serves the API on port 4002.
