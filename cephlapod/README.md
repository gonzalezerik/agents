# cephlapod

> **Work in progress — not running.** This is the orchestration harness that
> let coding agents run against a pool of local models on a multi-GPU
> server. It stopped when that server was rebuilt (late September 2026) and
> hasn't been redeployed. History here comes from the dashboard repo where
> it was built; the last commits sync the services with the versions that
> were deployed, recovered from a pre-rebuild snapshot.

Three parts:

- **`services/mc-shim/`** (Python, FastAPI). Speaks the Anthropic Messages
  API, so a coding agent can point at it. It translates requests and
  streaming responses to OpenAI-compatible calls (`translator.py`), repairs
  malformed tool calls from local models (`tool_repair.py`), asks a small
  router model which pooled model should take the turn (`router.py`), and
  logs every session event (`event_log.py`).
- **`services/mc-agent/`** (Python, FastAPI). Runs on each GPU host:
  reports GPUs and VRAM (`gpu.py`), starts and stops `llama-server`
  processes for registry models (`launcher.py`), and serves the pool API
  the dashboard uses (`orchestrator.py`: pool state, host heartbeats,
  model settings, start/stop, a live routing-event stream).
- **`lib/orchestration/`** (TypeScript) plus the dashboard pages and API
  routes under `app/` and `components/`. A model registry, a desired-state
  store (which models should be in the pool, which one routes), a
  reconciler that diffs desired against observed state into start/stop
  actions, preemption planning when VRAM is short, Wake-on-LAN for sleeping
  hosts, and a routing log built from session events.

## Tests

Stage A characterization tests pin current behavior before any refactor:

```sh
npm install && npm test                                   # 34 vitest: reconciler, preemption
cd services/mc-shim && pip install -r requirements.txt pytest && pytest   # 59: translator, tool_repair
```

The original stage A also used private golden fixtures (the full
production registry and five recorded sessions); those aren't published.
The GPU UUIDs in the tests are placeholders.

## Known bugs (found by stage A, not fixed yet)

1. The reconciler's `restore` action is dead code: auto-resume pool members
   always get a `start` action instead.
2. The translator silently drops user text when one message contains both
   text and tool-result blocks.
3. `requires_gap` is always false with the real registry, because no model
   needs more VRAM than the total GPU capacity, so that preemption path
   never runs.

## What's left

Redeploy (or replace `mc-agent` with the server's current model-switching
setup), then the planned extraction stages after A: a standalone package
boundary, configuration instead of hard-coded hosts and ports, fixes for
the three bugs above, and documentation.
