import { getAgentRun, markRunApplied } from "@/lib/pg-client";
import { k8sDeletePod } from "@/lib/k8s-client";

export const dynamic = "force-dynamic";

/**
 * The one-click approval step. Only ever executes the one narrow,
 * pre-defined safe action (restart_pod -> delete the pod, let the
 * Deployment/ArgoCD recreate it) - anything else the agent proposed is
 * "manual", meaning a human does it themselves. No arbitrary command
 * execution here by design.
 */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await getAgentRun(id);
  if (!run) return Response.json({ error: "run not found" }, { status: 404 });
  if (run.applied_at) return Response.json({ error: "already applied" }, { status: 409 });

  const action = run.proposed_action;
  if (!action || action.type !== "restart_pod" || !action.namespace || !action.pod) {
    return Response.json({ error: "this run has no auto-applicable action - it needs a human to do it manually" }, { status: 400 });
  }

  const result = await k8sDeletePod(action.namespace, action.pod);
  const resultText = result.ok
    ? `Deleted pod ${action.namespace}/${action.pod} (HTTP ${result.status}) - it will be recreated by its Deployment/ReplicaSet.`
    : `Failed to delete pod ${action.namespace}/${action.pod} (HTTP ${result.status}).`;

  await markRunApplied(id, resultText, result.ok ? "executed" : "escalated");

  return Response.json({ ok: result.ok, result: resultText });
}
