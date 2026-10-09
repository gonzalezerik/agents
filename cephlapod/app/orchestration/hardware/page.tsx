"use client";

import { useState, useEffect } from "react";
import type { HostObservedState, GpuState } from "@/lib/orchestration/types";

export default function HardwarePage() {
  const [hosts, setHosts] = useState<HostObservedState[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function poll() {
      try {
        const res = await fetch("/api/orchestration/observed");
        setHosts(await res.json());
        setError(null);
      } catch (e) { setError(String(e)); }
    }
    poll();
    const id = setInterval(poll, 6_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[#D0D6E0]">Hardware</h1>
        {error && <span className="text-red-400 text-sm">{error}</span>}
      </div>

      {hosts.map((host) => (
        <HostCard key={host.host_id} host={host} />
      ))}

      {hosts.length === 0 && (
        <p className="text-[#62666D] text-sm">No hosts reachable</p>
      )}
    </div>
  );
}

function HostCard({ host }: { host: HostObservedState }) {
  return (
    <div className="rounded-lg border border-[#23252A] bg-[#0F1011] p-5 space-y-4">
      <div className="flex items-center gap-3">
        <div className={`h-2 w-2 rounded-full ${host.reachable ? "bg-green-400" : "bg-red-400"}`} />
        <h2 className="text-base font-semibold text-[#D0D6E0]">{host.host_id}</h2>
        <span className="text-xs text-[#62666D]">polled {new Date(host.polled_at).toLocaleTimeString()}</span>
        {host.agent_version && <span className="text-xs text-[#62666D]">v{host.agent_version}</span>}
      </div>

      {!host.reachable && (
        <p className="text-red-400 text-sm">Host unreachable</p>
      )}

      {/* GPU grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {host.gpus.map((gpu) => <GpuCard key={gpu.uuid} gpu={gpu} />)}
      </div>

      {/* Running models */}
      {host.running_models.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-[#8A8F98] uppercase tracking-wider">Running models</p>
          <div className="space-y-1">
            {host.running_models.map((m) => (
              <div key={m.model_id} className="flex items-center gap-3 px-3 py-2 rounded bg-[#23252A] text-sm">
                <div className={`h-2 w-2 rounded-full flex-shrink-0 ${
                  m.health === "healthy" ? "bg-green-400" :
                  m.health === "degraded" ? "bg-yellow-400" : "bg-red-400"
                }`} />
                <span className="text-[#D0D6E0] truncate font-mono text-xs">{m.model_id}</span>
                <span className="text-[#62666D] text-xs">pid {m.pid}</span>
                {m.tokens_sec && <span className="text-[#8A8F98] text-xs ml-auto">{m.tokens_sec.toFixed(1)} tok/s</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function GpuCard({ gpu }: { gpu: GpuState }) {
  const usedPct = Math.round((gpu.vram_used_mib / gpu.vram_total_mib) * 100);
  const barColor = usedPct > 90 ? "bg-red-400" : usedPct > 70 ? "bg-yellow-400" : "bg-[#7C87FF]";

  return (
    <div className="rounded-md bg-[#23252A] p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-[#D0D6E0]">{gpu.name}</p>
          <p className="text-xs text-[#62666D] font-mono">{gpu.uuid.slice(0, 20)}…</p>
        </div>
        <div className="text-right flex-shrink-0">
          <p className="text-xs text-[#8A8F98]">{gpu.temp_c}°C</p>
          <p className="text-xs text-[#8A8F98]">{gpu.util_pct}% util</p>
        </div>
      </div>

      {/* VRAM bar */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-[#8A8F98]">
          <span>VRAM</span>
          <span>{(gpu.vram_used_mib / 1024).toFixed(1)} / {(gpu.vram_total_mib / 1024).toFixed(0)} GB ({usedPct}%)</span>
        </div>
        <div className="h-1.5 rounded-full bg-[#0F1011] overflow-hidden">
          <div className={`h-full ${barColor} transition-all`} style={{ width: `${usedPct}%` }} />
        </div>
      </div>

      {/* Processes */}
      {gpu.processes.length > 0 && (
        <div className="space-y-1">
          {gpu.processes.map((p) => (
            <div key={p.pid} className="flex items-center justify-between text-xs">
              <span className={`truncate max-w-[180px] ${p.is_foreign ? "text-[#62666D]" : "text-[#D0D6E0]"}`}>
                {p.model_id ?? p.command.slice(0, 30)}
                {p.is_foreign && <span className="text-yellow-400 ml-1">[foreign]</span>}
              </span>
              <span className="text-[#8A8F98] ml-2 flex-shrink-0">{(p.vram_mib / 1024).toFixed(1)} GB</span>
            </div>
          ))}
        </div>
      )}

      {gpu.processes.length === 0 && (
        <p className="text-xs text-[#62666D]">No processes</p>
      )}
    </div>
  );
}
