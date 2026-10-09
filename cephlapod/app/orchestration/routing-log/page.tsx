"use client";

import { useState, useEffect } from "react";
import type { RoutingLogEntry } from "@/lib/orchestration/types";

const OUTCOME_COLORS: Record<string, string> = {
  success:     "text-green-400",
  timeout:     "text-yellow-400",
  repaired:    "text-orange-400",
  error:       "text-red-400",
  passthrough: "text-[#8A8F98]",
};

export default function RoutingLogPage() {
  const [entries, setEntries] = useState<RoutingLogEntry[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/orchestration/routing-log?limit=200")
      .then((r) => r.json())
      .then((d) => { setEntries(d); setLoading(false); });
    const id = setInterval(() =>
      fetch("/api/orchestration/routing-log?limit=200").then((r) => r.json()).then(setEntries), 10_000
    );
    return () => clearInterval(id);
  }, []);

  return (
    <div className="p-6 max-w-7xl">
      <h1 className="text-xl font-semibold text-[#D0D6E0] mb-6">Routing Log</h1>

      {loading && <p className="text-[#62666D] text-sm">Loading…</p>}

      <div className="space-y-1">
        {entries.map((e) => (
          <div key={e.id} className="rounded-lg border border-[#23252A] overflow-hidden">
            <button
              onClick={() => setExpanded(expanded === e.id ? null : e.id)}
              className="w-full flex items-center gap-4 px-4 py-3 hover:bg-[#23252A]/50 transition-colors text-left"
            >
              <span className="text-xs text-[#62666D] flex-shrink-0 w-36">
                {new Date(e.ts).toLocaleString()}
              </span>
              <span className={`text-xs font-medium flex-shrink-0 w-20 ${OUTCOME_COLORS[e.outcome] ?? "text-[#D0D6E0]"}`}>
                {e.outcome}
              </span>
              <span className="text-xs text-[#D0D6E0] truncate flex-1">
                {e.prompt_summary ?? "—"}
              </span>
              <span className="text-xs text-[#62666D] flex-shrink-0">
                {e.agent_model_id?.split(":")[1] ?? "—"}
              </span>
              {e.latency_agent_ms && (
                <span className="text-xs text-[#8A8F98] flex-shrink-0">{e.latency_agent_ms}ms</span>
              )}
            </button>

            {expanded === e.id && (
              <div className="border-t border-[#23252A] bg-[#08090A] px-4 py-3 grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                <Field label="Session" value={e.session_id} mono />
                <Field label="Orchestrator" value={e.orchestrator_model_id ?? "—"} mono />
                <Field label="Agent" value={e.agent_model_id ?? "—"} mono />
                <Field label="Routing reason" value={e.routing_reason ?? "—"} />
                <Field label="Plan latency" value={e.latency_plan_ms ? `${e.latency_plan_ms}ms` : "—"} />
                <Field label="Agent latency" value={e.latency_agent_ms ? `${e.latency_agent_ms}ms` : "—"} />
                <Field label="Tokens in" value={e.tokens_in?.toLocaleString() ?? "—"} />
                <Field label="Tokens out" value={e.tokens_out?.toLocaleString() ?? "—"} />
                {e.error_detail && (
                  <div className="col-span-4">
                    <p className="text-[#8A8F98] mb-1">Error</p>
                    <pre className="text-red-300 whitespace-pre-wrap">{e.error_detail}</pre>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {!loading && entries.length === 0 && (
          <p className="text-[#62666D] text-sm">No routing entries yet</p>
        )}
      </div>
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-[#8A8F98] mb-0.5">{label}</p>
      <p className={`text-[#D0D6E0] truncate ${mono ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}
