import { listActiveAlerts, type ActiveAlert } from "./alertmanager-client";
import { listPods, listRecentEvents } from "./k8s-client";
import { diagnose } from "./agent-llm";
import { insertAgentRun, type AgentRun } from "./pg-client";

/**
 * Investigate one active alert: gather real context (pod status, recent
 * events), ask the LLM to diagnose + propose a fix, log the run. Never
 * applies anything itself - that's a separate, explicit approval step
 * (see /api/agent/runs/[id]/apply).
 */
export async function investigateAlert(fingerprint: string): Promise<AgentRun | null> {
  const alerts = await listActiveAlerts();
  const alert = alerts?.find((a) => a.fingerprint === fingerprint);
  if (!alert) return null;

  const contextParts: string[] = [
    `Alert: ${alert.alertname}`,
    `Severity: ${alert.severity}`,
    `Summary: ${alert.summary}`,
    `Namespace: ${alert.namespace ?? "n/a"}`,
    `Firing since: ${alert.startsAt}`,
  ];

  let candidatePod: { namespace: string; name: string } | null = null;

  if (alert.namespace) {
    const pods = await listPods(alert.namespace);
    if (pods && pods.length > 0) {
      contextParts.push(
        "Pods in this namespace:",
        ...pods.map((p) => `  - ${p.name}: phase=${p.phase} ready=${p.ready} restarts=${p.restartCount}${p.reason ? ` reason=${p.reason}` : ""}`)
      );
      // Prefer a specifically-named pod from the alert label, else the first not-ready one
      const named = alert.pod ? pods.find((p) => p.name === alert.pod) : null;
      const unhealthy = pods.find((p) => !p.ready || p.phase !== "Running");
      const target = named ?? unhealthy;
      if (target) candidatePod = { namespace: alert.namespace, name: target.name };
    }

    const events = await listRecentEvents(alert.namespace, 8);
    if (events && events.length > 0) {
      contextParts.push(
        "Recent events:",
        ...events.map((e) => `  - [${e.lastTimestamp}] ${e.involvedObject} ${e.reason}: ${e.message} (x${e.count})`)
      );
    }
  }

  const context = contextParts.join("\n");
  const diagnosis = await diagnose(context);

  // Outcome:
  // - "proposed fix": diagnosis succeeded and there's a pod we can safely
  //   auto-restart - the normal one-click-approval path.
  // - "escalated": the agent has nothing safe to offer a human to just
  //   click through - either it couldn't diagnose at all (LLM unreachable),
  //   or it diagnosed a critical-severity alert with no auto-applicable fix.
  //   This is the only outcome that triggers the TakeoverModal.
  // - "investigated": diagnosis succeeded, no auto-applicable action, but
  //   not urgent enough (non-critical) to interrupt with a modal - sits in
  //   the timeline with a manual note instead.
  let outcome: string;
  if (!diagnosis) {
    outcome = "escalated";
  } else if (candidatePod) {
    outcome = "proposed fix";
  } else if (alert.severity === "critical") {
    outcome = "escalated";
  } else {
    outcome = "investigated";
  }

  const run = await insertAgentRun({
    entity: alert.namespace ?? alert.alertname,
    summary: diagnosis ? `Investigated ${alert.alertname}` : `Investigation failed for ${alert.alertname} (LLM unreachable)`,
    mode: "report-only",
    tool_access: "read-only",
    outcome,
    tool_name: "list_pods,list_events,llm_diagnose",
    confidence: diagnosis?.confidence ?? null,
    investigation: diagnosis?.investigation ?? `Could not reach the diagnostic LLM. Raw context:\n${context}`,
    proposed_action:
      diagnosis && candidatePod
        ? { type: "restart_pod", namespace: candidatePod.namespace, pod: candidatePod.name, label: diagnosis.proposedFix }
        : diagnosis
          ? { type: "manual", label: diagnosis.proposedFix }
          : null,
  });

  return run;
}

export async function getInvestigableAlerts(): Promise<ActiveAlert[]> {
  return (await listActiveAlerts()) ?? [];
}
