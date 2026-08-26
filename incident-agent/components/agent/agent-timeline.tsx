"use client";

import { useEffect, useState } from "react";
import { StatusIndicator } from "@/components/ui/status-indicator";

interface AgentRun {
  id: string;
  created_at: string;
  entity: string;
  summary: string;
  mode: string;
  tool_access: string;
  outcome: string;
  tool_name: string | null;
  confidence: number | null;
  investigation: string | null;
  proposed_action: { type: string; namespace?: string; pod?: string; label?: string } | null;
  applied_at: string | null;
  applied_result: string | null;
}

export function AgentTimeline({ refreshKey }: { refreshKey?: number }) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [applying, setApplying] = useState<string | null>(null);

  const load = () => {
    fetch("/api/agent/runs")
      .then((r) => r.json())
      .then((d) => setRuns(d.runs ?? []))
      .catch(() => {});
  };

  useEffect(load, [refreshKey]);

  const apply = async (id: string) => {
    setApplying(id);
    await fetch(`/api/agent/runs/${id}/apply`, { method: "POST" });
    setApplying(null);
    load();
  };

  return (
    <div className="p-6">
      <h2 className="text-xl font-semibold text-[#D0D6E0] mb-6">Agent Activity ({runs.length})</h2>

      {runs.length === 0 && (
        <p className="text-sm text-[#62666D]">No runs yet — investigate a firing alert above to see one here.</p>
      )}

      <div className="space-y-6">
        {runs.map((run) => (
          <div key={run.id} className="flex gap-4 group">
            <div className="flex flex-col items-center pt-1">
              <div className="h-full w-px bg-[#23252A]"></div>
              <div
                className={`h-3 w-3 rounded-full mt-1 ${
                  run.outcome === "executed" ? "bg-[#7C87FF]" : run.outcome === "escalated" ? "bg-[#F0553F]" : "bg-[#40C463]"
                }`}
              ></div>
            </div>

            <div className="flex-1 pb-6">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-[#62666D]">{new Date(run.created_at).toLocaleString()}</span>
                  <span className="px-2 py-0.5 rounded text-xs font-medium bg-[#62666D]/10 text-[#62666D]">{run.mode}</span>
                  <span className="px-2 py-0.5 rounded text-xs font-medium bg-[#40C463]/10 text-[#40C463]">{run.tool_access}</span>
                </div>
                <span
                  className={`px-2 py-0.5 rounded text-xs ${
                    run.outcome === "executed" ? "bg-[#7C87FF]/10 text-[#7C87FF]" : run.outcome === "escalated" ? "bg-[#F0553F]/10 text-[#F0553F]" : "bg-[#40C463]/10 text-[#40C463]"
                  }`}
                >
                  {run.outcome}
                </span>
              </div>

              <div className="flex items-center gap-2 mb-2">
                <StatusIndicator status="agent" size="sm" withLabel={false} />
                <span className="text-sm text-[#D0D6E0]">{run.summary}</span>
                <span className="px-2 py-0.5 rounded text-xs bg-[#1D1F21] text-[#8A8F98]">{run.entity}</span>
              </div>

              {run.confidence !== null && (
                <div className="text-xs text-[#62666D] font-mono mb-2">
                  Tool: {run.tool_name} | Confidence: {(run.confidence * 100).toFixed(0)}%
                </div>
              )}

              <button
                onClick={() => setExpanded(expanded === run.id ? null : run.id)}
                className="text-xs text-[#62666D] hover:text-[#7C87FF]"
              >
                {expanded === run.id ? "Hide details" : "View details"}
              </button>

              {expanded === run.id && (
                <div className="mt-3 bg-[#0F1011] border border-[#23252A] rounded-md p-3 space-y-2 text-sm">
                  <div>
                    <div className="text-xs text-[#62666D] mb-1">Investigation</div>
                    <div className="text-[#D0D6E0] whitespace-pre-wrap">{run.investigation}</div>
                  </div>
                  {run.proposed_action && (
                    <div>
                      <div className="text-xs text-[#62666D] mb-1">Proposed fix</div>
                      <div className="text-[#D0D6E0]">{run.proposed_action.label}</div>
                      {run.proposed_action.type === "restart_pod" && (
                        <div className="text-xs text-[#62666D] font-mono mt-1">
                          → delete pod {run.proposed_action.namespace}/{run.proposed_action.pod}
                        </div>
                      )}
                    </div>
                  )}
                  {run.applied_at ? (
                    <div className="pt-2 border-t border-[#23252A]">
                      <div className="text-xs text-[#62666D] mb-1">Applied {new Date(run.applied_at).toLocaleString()}</div>
                      <div className="text-[#D0D6E0] text-xs">{run.applied_result}</div>
                    </div>
                  ) : run.proposed_action?.type === "restart_pod" ? (
                    <button
                      onClick={() => apply(run.id)}
                      disabled={applying === run.id}
                      className="mt-2 px-3 py-1.5 rounded-md bg-[#7C87FF] text-[#08090A] text-xs font-medium hover:bg-[#6B76E0] transition-colors disabled:opacity-50"
                    >
                      {applying === run.id ? "Applying…" : "Approve & apply"}
                    </button>
                  ) : run.proposed_action ? (
                    <div className="text-xs text-[#62666D] pt-2 border-t border-[#23252A]">
                      No safe auto-apply for this one — needs manual action.
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
