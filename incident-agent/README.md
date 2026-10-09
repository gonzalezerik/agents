# incident-agent

> **Work in progress.** Deployed inside a private ops dashboard, but its
> model endpoint has been down since a GPU-server rebuild (late September
> 2026), so every investigation currently ends as "escalated". These files
> are extracted from that Next.js app with their commit history; they are a
> reference implementation, not a package.

An ops agent for a small Kubernetes homelab: when an alert fires, it gathers
evidence, asks a model what's wrong, and proposes a fix that a human can
approve with one click — but only for the one action it is allowed to take.

## The flow

1. **Alerts** (`lib/alertmanager-client.ts`). Active alerts come from
   Alertmanager; the Agent Center page (`app/agent/page.tsx`) lists them.
2. **Investigate** (`lib/agent-investigate.ts`). For one alert: the alert
   itself, every pod in its namespace (phase, readiness, restarts, reason)
   and the namespace's recent events (`lib/k8s-client.ts`). The candidate
   pod is the one named in the alert, else the first unhealthy one.
3. **Diagnose** (`lib/agent-llm.ts`). An OpenAI-compatible model returns a
   root-cause analysis, one proposed fix, and a confidence, in labeled
   sections parsed in code.
4. **Record.** Every investigation becomes an `agent_runs` row
   (`lib/pg-client.ts`) with one of three outcomes:
   - `proposed fix` — diagnosed, and there is a pod that can safely be
     restarted;
   - `investigated` — diagnosed, but the fix is manual and the alert isn't
     critical;
   - `escalated` — the model couldn't be reached, or a critical alert has no
     safe automatic fix. This opens a takeover modal for a human, with the
     raw context attached.
5. **Approve** (`app/api/agent/runs/[id]/apply/route.ts`). The only action
   that can be applied automatically is deleting the target pod so its
   Deployment recreates it. Anything else is labeled for a human to do; there
   is no arbitrary command execution.

`evals/incident_investigation/tasks.json` holds eval cases for the graph
runtime's eval runner (see `../graph-runtime/`).

## Known gaps

- **Model endpoint down.** The default points at a GPU-server port that no
  longer serves since the rebuild; set `GPUHOST_LLM_URL` to a live
  OpenAI-compatible endpoint.
- **Free-text parsing.** The model answers in labeled sections parsed with
  regexes; schema-constrained output would remove a class of failures.
- **Shallow context.** No container logs, metrics, or recent deploy history
  go into the prompt yet — only pod state and events.
- **Two implementations.** The same investigation also exists as a graph in
  `../graph-runtime/` with an approval interrupt. Only one should survive.
- **No automated accessibility checks** for the Agent Center page yet.

## Configuration

`GPUHOST_LLM_URL`, `ALERTMANAGER_URL`, `DATABASE_URL`, plus an in-cluster
service account that can list pods and events and delete pods in the
watched namespaces. The UI imports the host app's `PageShell` and
`StatusPill` components, which are not included.
