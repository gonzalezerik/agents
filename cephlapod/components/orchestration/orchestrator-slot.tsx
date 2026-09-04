"use client";

import { useState } from "react";
import type { Model, OrchestratorSlot, HostObservedState } from "@/lib/orchestration/types";

interface Props {
  slot: OrchestratorSlot | null;
  models: Model[];
  observed: HostObservedState[];
  onSet: (model_id: string | null) => void;
}

export function OrchestratorSlotPanel({ slot, models, observed, onSet }: Props) {
  const [selecting, setSelecting] = useState(false);
  const [pending, setPending] = useState<string | null | "clear">(undefined as any);

  const eligible = models.filter((m) => m.role_tags.includes("orchestrator-eligible") && m.enabled);
  const currentModel = models.find((m) => m.id === slot?.model_id);

  const runningIds = new Set(observed.flatMap((h) => h.running_models.map((r) => r.model_id)));
  const isRunning = slot?.model_id ? runningIds.has(slot.model_id) : false;

  async function commit() {
    if (pending === undefined) return;
    onSet(pending === "clear" ? null : pending);
    setSelecting(false);
    setPending(undefined as any);
  }

  return (
    <div className="rounded-lg border border-[#23252A] bg-[#0F1011] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[#D0D6E0] uppercase tracking-wider">Orchestrator</h2>
        <button
          onClick={() => setSelecting(!selecting)}
          className="text-xs text-[#7C87FF] hover:text-[#a0aaff] transition-colors"
        >
          {selecting ? "Cancel" : "Change"}
        </button>
      </div>

      {/* Current slot */}
      <div className="flex items-center gap-3 p-3 rounded-md bg-[#23252A]">
        <div className={`h-2 w-2 rounded-full flex-shrink-0 ${
          !slot?.model_id ? "bg-[#62666D]" :
          isRunning ? "bg-green-400" : "bg-yellow-400"
        }`} />
        <div className="min-w-0">
          {currentModel ? (
            <>
              <p className="text-sm font-medium text-[#D0D6E0] truncate">{currentModel.name}</p>
              <p className="text-xs text-[#8A8F98] truncate">
                {currentModel.placement.host_id} · {currentModel.quant ?? "—"} ·{" "}
                {isRunning ? <span className="text-green-400">running</span> : <span className="text-yellow-400">not running</span>}
              </p>
            </>
          ) : (
            <p className="text-sm text-[#62666D]">No orchestrator set</p>
          )}
        </div>
      </div>

      {slot?.set_at && (
        <p className="text-xs text-[#62666D]">
          Set {new Date(slot.set_at).toLocaleString()} by {slot.set_by}
        </p>
      )}

      {/* Model picker */}
      {selecting && (
        <div className="space-y-2">
          <p className="text-xs text-[#8A8F98] uppercase tracking-wider">Select orchestrator</p>
          <div className="space-y-1 max-h-64 overflow-y-auto">
            <button
              onClick={() => setPending("clear")}
              className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                pending === "clear"
                  ? "bg-[#7C87FF]/20 text-[#7C87FF]"
                  : "text-[#62666D] hover:bg-[#23252A]"
              }`}
            >
              — Clear (no orchestrator)
            </button>
            {eligible.map((m) => {
              const running = runningIds.has(m.id);
              return (
                <button
                  key={m.id}
                  onClick={() => setPending(m.id)}
                  className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                    pending === m.id
                      ? "bg-[#7C87FF]/20 text-[#7C87FF]"
                      : "hover:bg-[#23252A] text-[#D0D6E0]"
                  }`}
                >
                  <span className={`inline-block h-1.5 w-1.5 rounded-full mr-2 ${running ? "bg-green-400" : "bg-[#62666D]"}`} />
                  {m.name}
                  <span className="text-xs text-[#8A8F98] ml-2">{m.placement.host_id}</span>
                </button>
              );
            })}
          </div>
          <button
            onClick={commit}
            disabled={pending === undefined}
            className="w-full py-2 rounded bg-[#7C87FF] text-white text-sm font-medium hover:bg-[#6b76ee] disabled:opacity-40 transition-colors"
          >
            Apply
          </button>
        </div>
      )}
    </div>
  );
}
