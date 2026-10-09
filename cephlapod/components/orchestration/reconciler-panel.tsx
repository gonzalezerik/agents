"use client";

import type { ReconcilerState } from "@/lib/orchestration/types";

interface Props {
  state: ReconcilerState | null;
  onReconcile: () => void;
  onToggleFreeze: () => void;
}

export function ReconcilerPanel({ state, onReconcile, onToggleFreeze }: Props) {
  if (!state) return null;
  return (
    <div className="rounded-lg border border-[#23252A] bg-[#0F1011] p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[#D0D6E0] uppercase tracking-wider">Reconciler</h2>
        <div className="flex gap-2">
          <button
            onClick={onToggleFreeze}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              state.frozen
                ? "bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30"
                : "bg-[#23252A] text-[#8A8F98] hover:text-[#D0D6E0]"
            }`}
          >
            {state.frozen ? "Frozen — Click to unfreeze" : "Freeze"}
          </button>
          <button
            onClick={onReconcile}
            disabled={state.frozen}
            className="px-3 py-1.5 rounded text-xs font-medium bg-[#7C87FF]/20 text-[#7C87FF] hover:bg-[#7C87FF]/30 disabled:opacity-40 transition-colors"
          >
            Reconcile now
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <Stat label="Status" value={state.frozen ? "Frozen" : "Active"} accent={state.frozen ? "yellow" : "green"} />
        <Stat label="Transitions / min" value={String(state.transition_count_last_minute)} />
        <Stat label="Last run" value={state.last_run ? new Date(state.last_run).toLocaleTimeString() : "—"} />
        <Stat label="Last error" value={state.last_error ? "Error" : "None"} accent={state.last_error ? "red" : undefined} title={state.last_error ?? undefined} />
      </div>

      {state.last_error && (
        <pre className="mt-3 p-3 rounded bg-red-900/20 text-red-300 text-xs overflow-x-auto whitespace-pre-wrap">
          {state.last_error}
        </pre>
      )}
    </div>
  );
}

function Stat({ label, value, accent, title }: { label: string; value: string; accent?: string; title?: string }) {
  const color =
    accent === "green" ? "text-green-400" :
    accent === "yellow" ? "text-yellow-400" :
    accent === "red" ? "text-red-400" :
    "text-[#D0D6E0]";
  return (
    <div title={title}>
      <p className="text-xs text-[#8A8F98] mb-1">{label}</p>
      <p className={`font-medium ${color}`}>{value}</p>
    </div>
  );
}
