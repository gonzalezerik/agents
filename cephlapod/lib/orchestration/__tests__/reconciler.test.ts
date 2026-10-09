/**
 * Characterization tests for reconciler.ts — documents current behavior as it exists today.
 * GPU UUIDs below are placeholders; VRAM figures match the real hardware.
 *
 * Do not modify tests to make them pass. A failing test after a move is a finding.
 * Suspected bugs are noted in comments but NOT fixed here.
 */
import { describe, it, expect, beforeAll, beforeEach } from "vitest";
import { getDb } from "@/lib/orchestration/db";
import { upsertModel } from "@/lib/orchestration/model-registry";
import { setOrchestrator, addToAgentPool, listAgentPool } from "@/lib/orchestration/desired-state";
import { computeDiff, getReconcilerState, setFreeze } from "@/lib/orchestration/reconciler";
import type { HostObservedState, Model } from "@/lib/orchestration/types";

// ── GPU UUIDs (placeholders for the GPU host's cards) ────────────────────
const A100_1 = "GPU-a1000001-0000-0000-0000-000000000000";
const A100_2 = "GPU-a1000002-0000-0000-0000-000000000000";
const RTX3090 = "GPU-30900001-0000-0000-0000-000000000000";

// ── Model fixtures (subset of the 57-entry production registry) ───────────────

const NEMOTRON: Omit<Model, "created_at" | "updated_at"> = {
  id: "gpuhost:nemotron-lightning",
  name: "Nemotron Lightning 30B A3B",
  backend: "llama.cpp",
  weights_path: "/home/erikg/models/nemotron-lightning/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Q8_0.gguf",
  quant: "Q8_0",
  placement: {
    host_id: "gpuhost", gpus: [A100_1], mode: "single",
    vram_req: { [A100_1]: 34816 },
    llama_tree: "opt", llama_binary: "/opt/llama.cpp/build/bin/llama-server",
    launch_args: "--n-gpu-layers 999 --ctx-size 131072",
  },
  capability: {
    param_count: "30B", tool_calling: "verified", tokens_sec: null, ctx_len: 131072,
    specialties: ["reasoning", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
  },
  role_tags: ["orchestrator-eligible", "agent-eligible"],
  enabled: true,
  notes: null,
};

const GEMMA4: Omit<Model, "created_at" | "updated_at"> = {
  id: "gpuhost:gemma4-12b",
  name: "Gemma 4 12B (RTX 3090)",
  backend: "llama.cpp",
  weights_path: "/home/erikg/models/gemma4-12b/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
  quant: "UD-Q4_K_XL",
  placement: {
    host_id: "gpuhost", gpus: [RTX3090], mode: "single",
    vram_req: { [RTX3090]: 8192 },
    llama_tree: "opt", llama_binary: "/opt/llama.cpp/build/bin/llama-server",
    launch_args: "--n-gpu-layers 999 --ctx-size 262144 --jinja",
  },
  capability: {
    param_count: "12B", tool_calling: "unverified", tokens_sec: null, ctx_len: 262144,
    specialties: ["vision"], has_vision: true, has_mmproj: true,
    mmproj_path: "/home/erikg/models/gemma4-12b/mmproj-F16.gguf",
  },
  role_tags: ["agent-eligible"],
  enabled: true,
  notes: null,
};

const QWEN_CPU: Omit<Model, "created_at" | "updated_at"> = {
  id: "gpuhost:qwen3.6-35b-a3b-cpu",
  name: "Qwen 3.6 35B A3B Q8 (CPU-only)",
  backend: "llama.cpp",
  weights_path: "/home/erikg/models/qwen3.6-35b-a3b-gguf/Qwen3.6-35B-A3B-Q8_0.gguf",
  quant: "Q8_0",
  placement: {
    host_id: "gpuhost", gpus: [], mode: "cpu",
    vram_req: {},
    llama_tree: "system", llama_binary: "/usr/local/bin/llama-server",
    launch_args: "--n-gpu-layers 0 --ctx-size 131072 --threads 32",
  },
  capability: {
    param_count: "35B", tool_calling: "verified", tokens_sec: null, ctx_len: 131072,
    specialties: ["reasoning", "function-calling", "code"], has_vision: false, has_mmproj: false, mmproj_path: null,
  },
  role_tags: ["orchestrator-eligible", "agent-eligible"],
  enabled: true,
  notes: null,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function emptyObserved(): HostObservedState[] {
  return [{
    host_id: "gpuhost",
    polled_at: new Date().toISOString(),
    reachable: true,
    gpus: [
      { uuid: A100_1, name: "A100 80GB", index: 0, vram_total_mib: 81920, vram_used_mib: 0, util_pct: 0, temp_c: 40, processes: [] },
      { uuid: A100_2, name: "A100 80GB", index: 1, vram_total_mib: 81920, vram_used_mib: 0, util_pct: 0, temp_c: 40, processes: [] },
      { uuid: RTX3090, name: "RTX 3090", index: 2, vram_total_mib: 24576, vram_used_mib: 0, util_pct: 0, temp_c: 45, processes: [] },
    ],
    running_models: [],
    agent_version: "0.1.0",
  }];
}

function observedWithRunning(model_ids: string[]): HostObservedState[] {
  const obs = emptyObserved();
  obs[0].running_models = model_ids.map((mid) => ({
    model_id: mid,
    pid: 10000 + model_ids.indexOf(mid),
    gpus: mid.includes("nemotron") ? [A100_1]
        : mid.includes("gemma") ? [RTX3090]
        : mid.includes("cpu") ? []
        : [A100_1, A100_2],
    health: "healthy" as const,
    tokens_sec: null,
    queue_depth: 0,
    started_at: new Date().toISOString(),
  }));
  return obs;
}

function clearDesiredState() {
  const db = getDb();
  db.prepare("DELETE FROM agent_pool").run();
  db.prepare("UPDATE orchestrator_slot SET model_id = NULL, set_at = datetime('now'), set_by = 'test' WHERE id = 1").run();
  db.prepare("UPDATE reconciler_state SET frozen = 0, transition_count_last_minute = 0, last_transition_window_start = NULL WHERE id = 1").run();
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeAll(() => {
  upsertModel(NEMOTRON);
  upsertModel(GEMMA4);
  upsertModel(QWEN_CPU);
});

beforeEach(() => {
  clearDesiredState();
});

// ── computeDiff() ─────────────────────────────────────────────────────────────

describe("computeDiff", () => {
  it("empty desired + nothing running → no actions", () => {
    const actions = computeDiff(emptyObserved());
    expect(actions).toEqual([]);
  });

  it("orchestrator desired and not running → start action", () => {
    setOrchestrator(NEMOTRON.id);
    const actions = computeDiff(emptyObserved());
    expect(actions).toContainEqual({ type: "start", model_id: NEMOTRON.id });
  });

  it("orchestrator desired and already running → no action", () => {
    setOrchestrator(NEMOTRON.id);
    const actions = computeDiff(observedWithRunning([NEMOTRON.id]));
    expect(actions).toEqual([]);
  });

  it("orchestrator null → no start action for orchestrator", () => {
    setOrchestrator(null);
    const actions = computeDiff(emptyObserved());
    expect(actions).toEqual([]);
  });

  it("pool member not running → start action", () => {
    addToAgentPool(GEMMA4.id, false);
    const actions = computeDiff(emptyObserved());
    expect(actions).toContainEqual({ type: "start", model_id: GEMMA4.id });
  });

  it("pool member already running → no action", () => {
    addToAgentPool(GEMMA4.id, false);
    const actions = computeDiff(observedWithRunning([GEMMA4.id]));
    expect(actions).toEqual([]);
  });

  it("multiple pool members, some running → only start the stopped ones", () => {
    addToAgentPool(GEMMA4.id, false);
    addToAgentPool(QWEN_CPU.id, false);
    const actions = computeDiff(observedWithRunning([GEMMA4.id]));
    expect(actions).toContainEqual({ type: "start", model_id: QWEN_CPU.id });
    const gemmaStart = actions.find((a) => a.type === "start" && a.model_id === GEMMA4.id);
    expect(gemmaStart).toBeUndefined();
  });

  it("orchestrator + pool members, all not running → start all", () => {
    setOrchestrator(NEMOTRON.id);
    addToAgentPool(GEMMA4.id, false);
    addToAgentPool(QWEN_CPU.id, false);
    const actions = computeDiff(emptyObserved());
    const startIds = actions.filter((a) => a.type === "start").map((a) => a.model_id);
    expect(startIds).toContain(NEMOTRON.id);
    expect(startIds).toContain(GEMMA4.id);
    expect(startIds).toContain(QWEN_CPU.id);
  });

  it("auto_resume pool member not running → start action (NOT restore)", () => {
    // BUG: The auto-resume loop appends a 'restore' action only if no 'start' was already added.
    // But the pool loop above it ALWAYS adds a 'start' for any non-running pool member.
    // Therefore 'restore' is dead code — auto_resume=true produces a 'start' action, not 'restore'.
    addToAgentPool(GEMMA4.id, true);
    const actions = computeDiff(emptyObserved());
    const startAction = actions.find((a) => a.type === "start" && a.model_id === GEMMA4.id);
    const restoreAction = actions.find((a) => a.type === "restore" && a.model_id === GEMMA4.id);
    expect(startAction).toBeDefined();
    expect(restoreAction).toBeUndefined(); // 'restore' never emitted; see bug note above
  });

  it("auto_resume pool member already running → no action", () => {
    addToAgentPool(GEMMA4.id, true);
    const actions = computeDiff(observedWithRunning([GEMMA4.id]));
    expect(actions).toEqual([]);
  });

  it("computeDiff never produces stop actions", () => {
    // Stop actions are sent from explicit API calls only; computeDiff only produces start/restore.
    // A model running on a GPU that is NOT in desired state is simply ignored.
    setOrchestrator(NEMOTRON.id);
    // GEMMA4 is running but not in desired state
    const actions = computeDiff(observedWithRunning([NEMOTRON.id, GEMMA4.id]));
    const stopActions = actions.filter((a) => a.type === "stop");
    expect(stopActions).toEqual([]);
  });

  it("model on foreign host does not affect gpuhost desired state", () => {
    // The reconciler only sees running_models in the observed state;
    // it does not check whether the running model's host_id matches.
    setOrchestrator(NEMOTRON.id);
    const obs = emptyObserved();
    // NEMOTRON appears as running on gpuhost (even though its host is gpuhost)
    obs[0].running_models = [{ model_id: NEMOTRON.id, pid: 1234, gpus: [A100_1], health: "healthy", tokens_sec: null, queue_depth: 0, started_at: "" }];
    const actions = computeDiff(obs);
    expect(actions).toEqual([]);
  });
});

// ── Freeze behavior ───────────────────────────────────────────────────────────

describe("reconciler freeze", () => {
  it("getReconcilerState returns frozen=false by default", () => {
    const state = getReconcilerState();
    expect(state.frozen).toBe(false);
  });

  it("setFreeze(true) → getReconcilerState.frozen=true", () => {
    setFreeze(true);
    expect(getReconcilerState().frozen).toBe(true);
  });

  it("setFreeze(false) → getReconcilerState.frozen=false", () => {
    setFreeze(true);
    setFreeze(false);
    expect(getReconcilerState().frozen).toBe(false);
  });
});
