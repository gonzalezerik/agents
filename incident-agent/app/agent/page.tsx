"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "@/components/ui/sidebar";
import { TopBar } from "@/components/ui/topbar";
import { AgentTimeline } from "@/components/agent/agent-timeline";
import { TakeoverModal } from "@/components/agent/takeover-modal";
import { StatusIndicator } from "@/components/ui/status-indicator";

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
  const [sidebarOpen, setSidebarOpen] = useState(true);
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
      <Sidebar isOpen={sidebarOpen} />
      <div className="flex flex-col flex-1 min-w-0 bg-[#08090A]">
        <TopBar sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(!sidebarOpen)} />
        <main className="flex-1 overflow-y-auto p-6">
          <div className="mb-6">
            <h1 className="text-2xl font-semibold text-[#D0D6E0] mb-2">Agent Center</h1>
            <div className="flex items-center gap-3 text-sm text-[#8A8F98]">
              <span className="px-3 py-1 rounded bg-[#62666D]/10 text-[#62666D] border border-[#23252A]">Mode: report-only</span>
              <span className="px-3 py-1 rounded bg-[#F0553F]/10 text-[#F0553F] border border-[#23252A]">
                Auto-apply: disabled (one-click approval required)
              </span>
            </div>
            <p className="mt-2 text-[#62666D]">
              Investigates real firing alerts using the homelab&apos;s own LLM (gpuhost) + live pod/event data. Never
              applies a fix without an explicit click.
            </p>
          </div>

          {/* Firing alerts - investigate trigger */}
          <div className="mb-8">
            <h2 className="text-lg font-medium text-[#D0D6E0] mb-3">Firing Alerts ({alerts.length})</h2>
            {alerts.length === 0 ? (
              <p className="text-sm text-[#62666D]">Nothing firing right now.</p>
            ) : (
              <div className="space-y-2">
                {alerts.map((a) => (
                  <div key={a.fingerprint} className="bg-[#0F1011] rounded-lg border border-[#23252A] p-3 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <StatusIndicator status={a.severity === "critical" ? "down" : "degraded"} size="sm" withLabel={false} />
                      <span className="text-sm text-[#D0D6E0]">{a.alertname}</span>
                      <span className="text-xs text-[#62666D] font-mono">{a.namespace ?? "-"}</span>
                    </div>
                    <button
                      onClick={() => investigate(a.fingerprint)}
                      disabled={investigating === a.fingerprint}
                      className="px-3 py-1.5 rounded-md bg-[#7C87FF] text-[#08090A] text-xs font-medium hover:bg-[#6B76E0] transition-colors disabled:opacity-50"
                    >
                      {investigating === a.fingerprint ? "Investigating…" : "Investigate"}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <AgentTimeline refreshKey={refreshKey} />
        </main>
      </div>

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
