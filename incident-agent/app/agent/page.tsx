"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/ui/page-shell";
import { AgentTimeline } from "@/components/agent/agent-timeline";
import { TakeoverModal } from "@/components/agent/takeover-modal";
import { StatusPill } from "@/components/ui/status-pill";

interface ActiveAlert {
  fingerprint: string;
  alertname: string;
  severity: string;
  namespace: string | null;
  summary: string;
}

interface AgentRun {
  id: string;
  created_at: string;
  entity: string;
  summary: string;
  outcome: string;
  investigation: string | null;
  applied_at: string | null;
}

export default function AgentCenterPage() {
  const [alerts, setAlerts] = useState<ActiveAlert[]>([]);
  const [investigating, setInvestigating] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [escalated, setEscalated] = useState<AgentRun[]>([]);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    fetch("/api/agent/alerts")
      .then((r) => r.json())
      .then((d) => setAlerts(d.alerts ?? []))
      .catch(() => {});
  }, [refreshKey]);

  useEffect(() => {
    fetch("/api/agent/runs")
      .then((r) => r.json())
      .then((d) => setEscalated((d.runs ?? []).filter((r: AgentRun) => r.outcome === "escalated" && !r.applied_at)))
      .catch(() => {});
  }, [refreshKey]);

  const investigate = async (fingerprint: string) => {
    setInvestigating(fingerprint);
    await fetch("/api/agent/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fingerprint }),
    });
    setInvestigating(null);
    setRefreshKey((k) => k + 1);
  };

  return (
    <>
      <PageShell breadcrumb="Agent" title="Agent Center">
        <div className="mb-6">
          <div className="flex items-center gap-3 text-sm text-[oklch(0.68_0.010_260)]">
            <span className="px-3 py-1 rounded-xl bg-white/5 border border-white/10 text-[oklch(0.54_0.008_260)]">Mode: report-only</span>
            <span className="px-3 py-1 rounded-xl bg-[oklch(0.50_0.21_22)]/10 text-[oklch(0.50_0.21_22)] border border-[oklch(0.50_0.21_22)]/20">
              Auto-apply: disabled (one-click approval required)
            </span>
          </div>
          <p className="mt-2 text-[oklch(0.54_0.008_260)]">
            Investigates real firing alerts using the homelab&apos;s own LLM (gpuhost) + live pod/event data. Never
            applies a fix without an explicit click.
          </p>
        </div>

        {/* Firing alerts - investigate trigger */}
        <div className="mb-8">
          <h2 className="text-lg font-medium text-white mb-3">Firing Alerts ({alerts.length})</h2>
          {alerts.length === 0 ? (
            <p className="text-sm text-[oklch(0.54_0.008_260)]">Nothing firing right now.</p>
          ) : (
            <div className="space-y-2">
              {alerts.map((a) => (
                <div key={a.fingerprint} className="surface-card p-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <StatusPill status={a.severity === "critical" ? "down" : "degraded"} size="sm" />
                    <span className="text-sm text-white">{a.alertname}</span>
                    <span className="text-xs text-[oklch(0.54_0.008_260)] font-mono">{a.namespace ?? "-"}</span>
                  </div>
                  <button
                    onClick={() => investigate(a.fingerprint)}
                    disabled={investigating === a.fingerprint}
                    className="px-3 py-1.5 rounded-xl grad-primary text-white text-xs font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
                  >
                    {investigating === a.fingerprint ? "Investigating…" : "Investigate"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <AgentTimeline refreshKey={refreshKey} />
      </PageShell>

      {escalated.length > 0 && !dismissed && (
        <TakeoverModal
          incidents={escalated.map((r) => ({
            id: r.id.slice(0, 8),
            title: r.summary,
            entity: r.entity,
            summary: r.investigation ?? "",
            opened: new Date(r.created_at).toLocaleString(),
          }))}
          onAcknowledge={() => setDismissed(true)}
        />
      )}
    </>
  );
}
