"use client";

import { useState, useEffect, useCallback } from "react";
import type {
  Model, OrchestratorSlot, AgentPoolEntry, HostObservedState,
  ReconcilerState, PreemptionPreview,
} from "@/lib/orchestration/types";

// ── sub-panels ────────────────────────────────────────────────────────────────
import { OrchestratorSlotPanel } from "@/components/orchestration/orchestrator-slot";
import { AgentPoolPanel } from "@/components/orchestration/agent-pool";
import { ReconcilerPanel } from "@/components/orchestration/reconciler-panel";

const POLL_MS = 8_000;

export default function OrchestrationPage() {
  const [models, setModels]               = useState<Model[]>([]);
  const [slot, setSlot]                   = useState<OrchestratorSlot | null>(null);
  const [pool, setPool]                   = useState<AgentPoolEntry[]>([]);
  const [observed, setObserved]           = useState<HostObservedState[]>([]);
  const [reconciler, setReconciler]       = useState<ReconcilerState | null>(null);
  const [loading, setLoading]             = useState(true);
  const [error, setError]                 = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [mRes, dRes, oRes, rRes] = await Promise.all([
        fetch("/api/orchestration/models"),
        fetch("/api/orchestration/desired"),
        fetch("/api/orchestration/observed"),
        fetch("/api/orchestration/reconcile"),
      ]);
      const [mData, dData, oData, rData] = await Promise.all([
        mRes.json(), dRes.json(), oRes.json(), rRes.json(),
      ]);
      setModels(mData);
      setSlot(dData.orchestrator);
      setPool(dData.agent_pool);
      setObserved(oData);
      setReconciler(rData);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  async function setOrchestrator(model_id: string | null) {
    await fetch("/api/orchestration/desired/orchestrator", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id }),
    });
    refresh();
  }

  async function addAgent(model_id: string) {
    await fetch("/api/orchestration/desired/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id }),
    });
    refresh();
  }

  async function removeAgent(model_id: string) {
    await fetch(`/api/orchestration/desired/agents/${encodeURIComponent(model_id)}`, { method: "DELETE" });
    refresh();
  }

  async function triggerReconcile() {
    await fetch("/api/orchestration/reconcile", { method: "POST" });
    refresh();
  }

  async function toggleFreeze() {
    await fetch("/api/orchestration/reconcile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frozen: !reconciler?.frozen }),
    });
    refresh();
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-[#8A8F98]">Loading orchestration state…</div>
  );

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[#D0D6E0]">Orchestration</h1>
        {error && <span className="text-red-400 text-sm">{error}</span>}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <OrchestratorSlotPanel
          slot={slot}
          models={models}
          observed={observed}
          onSet={setOrchestrator}
        />
        <AgentPoolPanel
          pool={pool}
          models={models}
          observed={observed}
          onAdd={addAgent}
          onRemove={removeAgent}
        />
      </div>

      <ReconcilerPanel
        state={reconciler}
        onReconcile={triggerReconcile}
        onToggleFreeze={toggleFreeze}
      />
    </div>
  );
}
