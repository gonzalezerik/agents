"use client";

import { useState } from "react";
import { StatusPill, Status } from "@/components/ui/status-pill";

interface Incident {
  id: string;
  title: string;
  severity: "critical" | "warning" | "info";
  affectedEntity: string;
  opened: string;
  closed?: string;
  status: "open" | "investigating" | "auto_resolved" | "escalated" | "closed";
  agentMode: string;
}

interface InvestigationStep {
  timestamp: string;
  tool: string;
  toolType: "read-log" | "query-metric" | "http-probe" | "get-pod-status";
  inputs: string;
  output: string;
  reasoning: string;
}

export function IncidentDetail({ incident }: { incident: Incident }) {
  const [activeTab, setActiveTab] = useState("transcript");

  const investigation: InvestigationStep[] = [
    {
      timestamp: "2026-07-29 02:14:25",
      tool: "query_loki",
      toolType: "read-log",
      inputs: "tenant=acme-lash, query='{job=\"booking-api\"} |~ \"connection.*timeout\" since=2h ago'",
      output: "Found 47 error lines in booking-api logs. Most recent: \"Connection timeout to upstream service at handler/booking.ts:45\"",
      reasoning: "Error logs show connection timeouts to upstream service. This is consistent with degraded status reported by health checks.",
    },
    {
      timestamp: "2026-07-29 02:14:30",
      tool: "get_pod_status",
      toolType: "get-pod-status",
      inputs: "namespace=acme-lash, pod=booking-api-7d9f8c6b5-x2k9p",
      output: "Pod status: Running, Restarts: 3 (last restart: 2h ago). Container status: Waiting (CrashLoopBackOff)",
      reasoning: "Pod is in CrashLoopBackOff state after 3 restarts. This explains the connection timeouts.",
    },
    {
      timestamp: "2026-07-29 02:14:35",
      tool: "query_prometheus",
      toolType: "query-metric",
      inputs: "query=sum(rate(http_requests_total{namespace=\"acme-lash\",status=~\"5..\"}[5m])) by (route)",
      output: "Rate of 5xx errors: 12 req/s on /api/booking endpoint. Error rate increased from 0.1% to 1.2% over past hour.",
      reasoning: "High error rate on booking endpoint confirms service degradation.",
    },
    {
      timestamp: "2026-07-29 02:14:40",
      tool: "get_recent_deploys",
      toolType: "http-probe",
      inputs: "argocd_app=acme-lash",
      output: "Last deploy: v3.0.0 at 2026-07-29 01:30:00. Sync status: Healthy. Revision: a1b2c3d",
      reasoning: "Incident started ~45 minutes after deploy v3.0.0. Correlation found between deploy and degradation.",
    },
  ];

  return (
    <div className="bg-[#0F1011] rounded-lg border border-[#23252A] overflow-hidden">
      {/* Header */}
      <div className="border-b border-[#23252A] p-4">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold text-[#D0D6E0]">Incident #{incident.id}</h2>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                incident.severity === "critical" ? "bg-[#F0553F]/10 text-[#F0553F]" :
                incident.severity === "warning" ? "bg-[#E6A100]/10 text-[#E6A100]" :
                "bg-[#40C463]/10 text-[#40C463]"
              }`}>
                {incident.severity.toUpperCase()}
              </span>
            </div>
            <div className="text-sm text-[#8A8F98]">{incident.title}</div>
            <div className="flex items-center gap-3 text-xs text-[#62666D]">
              <span>Affected: <span className="font-mono text-[#D0D6E0]">{incident.affectedEntity}</span></span>
              <span>Opened: {incident.opened}</span>
              {incident.closed && <span>Closed: {incident.closed}</span>}
              <span className={`px-2 py-0.5 rounded text-xs ${
                incident.status === "open" || incident.status === "investigating"
                  ? "bg-[#F0553F]/10 text-[#F0553F]"
                  : "bg-[#40C463]/10 text-[#40C463]"
              }`}>
                {incident.status.replace("_", " ")}
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            <button className="px-3 py-1.5 rounded border border-[#23252A] text-xs text-[#8A8F98] hover:bg-[#161718]">
              Close Incident
            </button>
            <button className="px-3 py-1.5 rounded bg-[#7C87FF] text-[#08090A] text-xs hover:bg-[#6B76E0]">
              Escalate
            </button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#23252A]">
        {["transcript", "fixes", "git", "provenance"].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium ${
              activeTab === tab
                ? "border-b-2 border-[#7C87FF] text-[#7C87FF]"
                : "text-[#8A8F98] hover:text-[#D0D6E0]"
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4">
        {activeTab === "transcript" && (
          <div className="space-y-6">
            <div className="bg-[#161718] rounded-lg p-3 text-xs text-[#8A8F98]">
              <p className="mb-2"><strong>Agent Mode:</strong> {incident.agentMode} at time of investigation</p>
              <p><strong>Decision:</strong> {incident.status === "auto_resolved" ? "Auto-resolved by playbook execution" : "Escalated to operator"}</p>
            </div>

            {investigation.map((step, i) => (
              <div key={i} className="border-l-2 border-[#23252A] pl-4">
                <div className="flex items-center gap-3 mb-2">
                  <span className="font-mono text-[#62666D]">{step.timestamp}</span>
                  <span className="px-2 py-0.5 rounded text-xs bg-[#1D1F21] text-[#8A8F98] font-mono">{step.tool}</span>
                  <span className="text-[#7C87FF]">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-3 w-3">
                      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                    </svg>
                  </span>
                </div>
                <div className="bg-[#1D1F21] rounded-lg p-3 text-xs font-mono mb-2 overflow-x-auto">
                  <div className="text-[#62666D] mb-1">INPUT</div>
                  <div className="text-[#D0D6E0]">{step.inputs}</div>
                </div>
                <div className="bg-[#1D1F21] rounded-lg p-3 text-xs font-mono mb-2 overflow-x-auto">
                  <div className="text-[#62666D] mb-1">OUTPUT</div>
                  <div className="text-[#8A8F98]">{step.output}</div>
                </div>
                <div className="bg-[#161718] rounded-lg p-2 text-xs text-[#D0D6E0]">
                  <span className="font-semibold text-[#7C87FF]">Reasoning:</span> {step.reasoning}
                </div>
              </div>
            ))}
          </div>
        )}

        {activeTab === "fixes" && (
          <div className="space-y-4">
            <div className="bg-[#161718] rounded-lg p-4 border border-[#23252A]">
              <div className="flex items-center gap-2 mb-3">
                <div className="h-8 w-8 rounded-full bg-[#F0553F]/10 flex items-center justify-center text-[#F0553F]">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
                  </svg>
                </div>
                <h3 className="font-medium text-[#D0D6E0]">Proposed Fix</h3>
              </div>
              <div className="text-sm text-[#8A8F98] mb-3">
                rollout_restart deployment/booking-api in namespace acme-lash
              </div>
              <div className="bg-[#1D1F21] rounded-lg p-2 text-xs font-mono mb-3">
                git diff --cached:
                <div className="text-[#40C463]">+ spec.template.spec.containers[0].image: acme-lash:v3.0.2</div>
                <div className="text-[#F0553F]">- spec.template.spec.containers[0].image: acme-lash:v3.0.0</div>
              </div>
              <div className="flex gap-2">
                <button className="px-3 py-1.5 rounded bg-[#7C87FF] text-[#08090A] text-xs hover:bg-[#6B76E0]">
                  Approve & Run
                </button>
                <button className="px-3 py-1.5 rounded border border-[#23252A] text-xs text-[#8A8F98] hover:bg-[#161718]">
                  Reject
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === "git" && (
          <div className="space-y-3">
            <div className="bg-[#1D1F21] rounded-lg p-3 text-xs font-mono">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[#7C87FF]">a1b2c3d</span>
                <span className="text-[#62666D]">Agent auto-committed changes</span>
              </div>
              <div className="text-[#8A8F98] mb-2">Update incident #a1 status to auto_resolved</div>
              <div className="flex gap-2 text-[#62666D]">
                <span>1 file changed</span>
                <span>2 insertions</span>
                <span>1 deletion</span>
              </div>
            </div>
            <div className="text-xs text-[#62666D]">
              <p>Full commit: <a href="#" className="text-[#7C87FF] hover:underline">a1b2c3d</a></p>
              <p>Repository: <span className="font-mono">homelab/ops</span></p>
            </div>
          </div>
        )}

        {activeTab === "provenance" && (
          <div className="space-y-4 text-sm">
            <div className="bg-[#1D1F21] rounded-lg p-3">
              <h3 className="text-xs font-semibold text-[#8A8F98] mb-2">Investigation Metadata</h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="block text-[#62666D] text-xs">Agent</span>
                  <span className="font-mono text-[#D0D6E0]">ops-agent-v1</span>
                </div>
                <div>
                  <span className="block text-[#62666D] text-xs">Model</span>
                  <span className="font-mono text-[#D0D6E0]">qwen3.6-35b-a3b</span>
                </div>
                <div>
                  <span className="block text-[#62666D] text-xs">Mode</span>
                  <span className="font-mono text-[#D0D6E0]">report-only</span>
                </div>
                <div>
                  <span className="block text-[#62666D] text-xs">Circuit Breakers</span>
                  <span className="font-mono text-[#40C463]">pass (0/2 actions)</span>
                </div>
              </div>
            </div>
            <div className="bg-[#1D1F21] rounded-lg p-3">
              <h3 className="text-xs font-semibold text-[#8A8F98] mb-2">Audit Information</h3>
              <div className="space-y-2 text-xs text-[#62666D]">
                <div className="flex justify-between">
                  <span>Log ID</span>
                  <span className="font-mono text-[#D0D6E0]">inc-2026-07-29-021422-a1</span>
                </div>
                <div className="flex justify-between">
                  <span>Immutable</span>
                  <span className="text-[#40C463]">Yes</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
