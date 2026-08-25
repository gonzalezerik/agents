"use client";

import { useState } from "react";
import { StatusIndicator, Status } from "@/components/ui/status-indicator";

type AgentMode = "report-only" | "playbook";
type ToolAccess = "read-only" | "write";
type ActionOutcome = "investigated" | "proposed fix" | "executed" | "escalated";

interface AgentRun {
  id: string;
  timestamp: string;
  summary: string;
  entity: string;
  mode: AgentMode;
  toolAccess: ToolAccess;
  outcome: ActionOutcome;
  toolName?: string;
  confidence?: number;
}

export function AgentTimeline() {
  const [filterMode, setFilterMode] = useState<AgentMode | "all">("all");
  const [filterOutcome, setFilterOutcome] = useState<ActionOutcome | "all">("all");

  const runs: AgentRun[] = [
    { id: "r1", timestamp: "2026-07-29 02:14:22", summary: "Investigated booking API degraded", entity: "lash", mode: "report-only", toolAccess: "read-only", outcome: "investigated", toolName: "query_loki", confidence: 0.85 },
    { id: "r2", timestamp: "2026-07-29 02:15:18", summary: "Proposed rollout_restart for booking-api", entity: "lash", mode: "report-only", toolAccess: "read-only", outcome: "proposed fix", confidence: 0.72 },
    { id: "r3", timestamp: "2026-07-29 01:30:15", summary: "Investigated auth-service latency", entity: "auth", mode: "report-only", toolAccess: "read-only", outcome: "investigated", toolName: "get_pod_status", confidence: 0.68 },
    { id: "r4", timestamp: "2026-07-29 00:45:33", summary: "Executed rollout_restart for inventory-sync", entity: "gardening", mode: "playbook", toolAccess: "write", outcome: "executed", toolName: "rollout_restart", confidence: 0.92 },
    { id: "r5", timestamp: "2026-07-28 22:10:00", summary: "Escalated database connection issue", entity: "tree", mode: "report-only", toolAccess: "read-only", outcome: "escalated", confidence: 0.45 },
    { id: "r6", timestamp: "2026-07-28 18:30:22", summary: "Investigated deployment failure", entity: "landscaping", mode: "report-only", toolAccess: "read-only", outcome: "investigated", toolName: "get_recent_deploys", confidence: 0.78 },
  ];

  const filteredRuns = runs.filter((run) => {
    const modeMatch = filterMode === "all" || run.mode === filterMode;
    const outcomeMatch = filterOutcome === "all" || run.outcome === filterOutcome;
    return modeMatch && outcomeMatch;
  });

  return (
    <div className="flex h-full">
      {/* Left Sidebar - Filters */}
      <div className="w-64 border-r border-[#23252A] p-4 space-y-6">
        <div>
          <h3 className="text-xs font-medium text-[#8A8F98] mb-2">Agent Mode</h3>
          <div className="space-y-2">
            <button
              onClick={() => setFilterMode("all")}
              className={`w-full text-left px-3 py-2 rounded text-sm ${
                filterMode === "all" ? "bg-[#1D1F21] text-[#D0D6E0]" : "text-[#8A8F98] hover:bg-[#161718]"
              }`}
            >
              All Modes
            </button>
            <button
              onClick={() => setFilterMode("report-only")}
              className={`w-full text-left px-3 py-2 rounded text-sm ${
                filterMode === "report-only" ? "bg-[#1D1F21] text-[#D0D6E0]" : "text-[#8A8F98] hover:bg-[#161718]"
              }`}
            >
              Report-Only
            </button>
            <button
              onClick={() => setFilterMode("playbook")}
              className={`w-full text-left px-3 py-2 rounded text-sm ${
                filterMode === "playbook" ? "bg-[#1D1F21] text-[#D0D6E0]" : "text-[#8A8F98] hover:bg-[#161718]"
              }`}
            >
              Playbook Mode
            </button>
          </div>
        </div>

        <div>
          <h3 className="text-xs font-medium text-[#8A8F98] mb-2">Outcome</h3>
          <div className="space-y-2">
            <button
              onClick={() => setFilterOutcome("all")}
              className={`w-full text-left px-3 py-2 rounded text-sm ${
                filterOutcome === "all" ? "bg-[#1D1F21] text-[#D0D6E0]" : "text-[#8A8F98] hover:bg-[#161718]"
              }`}
            >
              All Outcomes
            </button>
            <button
              onClick={() => setFilterOutcome("investigated")}
              className={`w-full text-left px-3 py-2 rounded text-sm ${
                filterOutcome === "investigated" ? "bg-[#1D1F21] text-[#D0D6E0]" : "text-[#8A8F98] hover:bg-[#161718]"
              }`}
            >
              Investigated
            </button>
            <button
              onClick={() => setFilterOutcome("proposed fix")}
              className={`w-full text-left px-3 py-2 rounded text-sm ${
                filterOutcome === "proposed fix" ? "bg-[#1D1F21] text-[#D0D6E0]" : "text-[#8A8F98] hover:bg-[#161718]"
              }`}
            >
              Proposed Fix
            </button>
            <button
              onClick={() => setFilterOutcome("executed")}
              className={`w-full text-left px-3 py-2 rounded text-sm ${
                filterOutcome === "executed" ? "bg-[#1D1F21] text-[#D0D6E0]" : "text-[#8A8F98] hover:bg-[#161718]"
              }`}
            >
              Executed
            </button>
            <button
              onClick={() => setFilterOutcome("escalated")}
              className={`w-full text-left px-3 py-2 rounded text-sm ${
                filterOutcome === "escalated" ? "bg-[#1D1F21] text-[#D0D6E0]" : "text-[#8A8F98] hover:bg-[#161718]"
              }`}
            >
              Escalated
            </button>
          </div>
        </div>

        <div className="text-xs text-[#62666D]">
          <p className="mb-1">Total Runs: {runs.length}</p>
          <p>Filtered: {filteredRuns.length}</p>
        </div>
      </div>

      {/* Timeline */}
      <div className="flex-1 p-6">
        <h2 className="text-xl font-semibold text-[#D0D6E0] mb-6">Agent Activity</h2>

        <div className="space-y-6">
          {filteredRuns.map((run, i) => (
            <div key={run.id} className="flex gap-4 group">
              {/* Timeline Line */}
              <div className="flex flex-col items-center pt-1">
                <div className="h-full w-px bg-[#23252A]"></div>
                <div className={`h-3 w-3 rounded-full mt-1 ${
                  run.outcome === "executed" ? "bg-[#7C87FF]" :
                  run.outcome === "escalated" ? "bg-[#F0553F]" :
                  "bg-[#40C463]"
                }`}></div>
              </div>

              {/* Run Card */}
              <div className="flex-1 pb-6">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-[#62666D]">{run.timestamp}</span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      run.mode === "report-only"
                        ? "bg-[#62666D]/10 text-[#62666D]"
                        : "bg-[#7C87FF]/10 text-[#7C87FF]"
                    }`}>
                      {run.mode}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      run.toolAccess === "read-only"
                        ? "bg-[#40C463]/10 text-[#40C463]"
                        : "bg-[#F0553F]/10 text-[#F0553F]"
                    }`}>
                      {run.toolAccess}
                    </span>
                  </div>
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    run.outcome === "executed" ? "bg-[#7C87FF]/10 text-[#7C87FF]" :
                    run.outcome === "escalated" ? "bg-[#F0553F]/10 text-[#F0553F]" :
                    "bg-[#40C463]/10 text-[#40C463]"
                  }`}>
                    {run.outcome}
                  </span>
                </div>

                <div className="flex items-center gap-2 mb-2">
                  <StatusIndicator status="agent" size="sm" withLabel={false} />
                  <span className="text-sm text-[#D0D6E0]">{run.summary}</span>
                  <span className="px-2 py-0.5 rounded text-xs bg-[#1D1F21] text-[#8A8F98]">
                    {run.entity}
                  </span>
                </div>

                {run.toolName && (
                  <div className="text-xs text-[#62666D] font-mono mb-2">
                    Tool: {run.toolName} {run.confidence && `| Confidence: ${(run.confidence * 100).toFixed(0)}%`}
                  </div>
                )}

                <div className="flex gap-2 text-xs text-[#62666D]">
                  <button className="hover:text-[#7C87FF]">View details</button>
                  <span>•</span>
                  <button className="hover:text-[#7C87FF]">View incident</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
