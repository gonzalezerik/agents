"use client";

import { useState } from "react";
import type { Model, AgentPoolEntry, HostObservedState } from "@/lib/orchestration/types";

interface Props {
  pool: AgentPoolEntry[];
  models: Model[];
  observed: HostObservedState[];
  onAdd: (model_id: string) => void;
  onRemove: (model_id: string) => void;
}

export function AgentPoolPanel({ pool, models, observed, onAdd, onRemove }: Props) {
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");

  const poolIds = new Set(pool.map((e) => e.model_id));
  const runningIds = new Set(observed.flatMap((h) => h.running_models.map((r) => r.model_id)));

  const eligible = models.filter(
    (m) => m.role_tags.includes("agent-eligible") && m.enabled && !poolIds.has(m.id)
  );

  const filtered = search
    ? eligible.filter((m) => m.name.toLowerCase().includes(search.toLowerCase()) || m.placement.host_id.includes(search))
    : eligible;

  return (
    <div className="rounded-lg border border-[#23252A] bg-[#0F1011] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[#D0D6E0] uppercase tracking-wider">
          Agent Pool <span className="text-[#62666D] font-normal">({pool.length})</span>
        </h2>
        <button
          onClick={() => setAdding(!adding)}
          className="text-xs text-[#7C87FF] hover:text-[#a0aaff] transition-colors"
        >
          {adding ? "Done" : "+ Add"}
        </button>
      </div>

      {/* Pool entries */}
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {pool.length === 0 && (
          <p className="text-sm text-[#62666D] py-2">No agents in pool</p>
        )}
        {pool.map((entry) => {
          const m = models.find((x) => x.id === entry.model_id);
          const running = runningIds.has(entry.model_id);
          return (
            <div key={entry.model_id} className="flex items-center gap-3 px-3 py-2 rounded hover:bg-[#23252A] group">
              <div className={`h-2 w-2 rounded-full flex-shrink-0 ${running ? "bg-green-400" : "bg-[#62666D]"}`} />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-[#D0D6E0] truncate">{m?.name ?? entry.model_id}</p>
                <p className="text-xs text-[#8A8F98] truncate">
                  {m?.placement.host_id} · {m?.placement.mode} ·{" "}
                  {running ? <span className="text-green-400">running</span> : "stopped"}
                  {entry.auto_resume && <span className="text-[#7C87FF] ml-1">· auto-resume</span>}
                </p>
              </div>
              <button
                onClick={() => onRemove(entry.model_id)}
                className="opacity-0 group-hover:opacity-100 text-xs text-red-400 hover:text-red-300 transition-all"
              >
                Remove
              </button>
            </div>
          );
        })}
      </div>

      {/* Add picker */}
      {adding && (
        <div className="space-y-2 border-t border-[#23252A] pt-3">
          <input
            type="text"
            placeholder="Search models…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full px-3 py-2 rounded bg-[#23252A] text-sm text-[#D0D6E0] placeholder-[#62666D] border border-[#23252A] focus:border-[#7C87FF] outline-none"
          />
          <div className="space-y-1 max-h-52 overflow-y-auto">
            {filtered.slice(0, 30).map((m) => (
              <button
                key={m.id}
                onClick={() => { onAdd(m.id); setSearch(""); }}
                className="w-full text-left px-3 py-2 rounded hover:bg-[#23252A] text-sm text-[#D0D6E0] transition-colors"
              >
                <span className={`inline-block h-1.5 w-1.5 rounded-full mr-2 ${runningIds.has(m.id) ? "bg-green-400" : "bg-[#62666D]"}`} />
                {m.name}
                <span className="text-xs text-[#8A8F98] ml-2">{m.placement.host_id} · {m.placement.mode}</span>
              </button>
            ))}
            {filtered.length === 0 && <p className="text-sm text-[#62666D] px-3">No matching models</p>}
          </div>
        </div>
      )}
    </div>
  );
}
