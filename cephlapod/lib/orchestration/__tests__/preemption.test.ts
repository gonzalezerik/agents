/**
 * Characterization tests for preemption.ts — documents current behavior as it exists today.
 * GPU UUIDs below are placeholders; VRAM figures match the real hardware.
 *
 * Do not modify tests to make them pass. A failing test after a move is a finding.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { getDb } from "@/lib/orchestration/db";
import { upsertModel } from "@/lib/orchestration/model-registry";
import { addToAgentPool } from "@/lib/orchestration/desired-state";
import { computePreemptionPreview, computeBlocked } from "@/lib/orchestration/preemption";
import type { HostObservedState, Model } from "@/lib/orchestration/types";

// ── GPU UUIDs (placeholders for the GPU host's cards) ────────────────────
const A100_1 = "GPU-a1000001-0000-0000-0000-000000000000";
const A100_2 = "GPU-a1000002-0000-0000-0000-000000000000";
const RTX3090 = "GPU-30900001-0000-0000-0000-000000000000";

// GPU totals (MiB)
const A100_TOTAL = 81920;
const RTX_TOTAL  = 24576;

// ── Model fixtures ────────────────────────────────────────────────────────────

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
    launch_args: "",
  },
  capability: {
    param_count: "30B", tool_calling: "verified", tokens_sec: null, ctx_len: 131072,
    specialties: ["reasoning", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
  },
  role_tags: ["orchestrator-eligible", "agent-eligible"],
  enabled: true, notes: null,
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
    launch_args: "",
  },
  capability: {
    param_count: "12B", tool_calling: "unverified", tokens_sec: null, ctx_len: 262144,
    specialties: ["vision"], has_vision: true, has_mmproj: true,
    mmproj_path: "/home/erikg/models/gemma4-12b/mmproj-F16.gguf",
  },
  role_tags: ["agent-eligible"],
  enabled: true, notes: null,
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
  enabled: true, notes: null,
};

const LAGUNA: Omit<Model, "created_at" | "updated_at"> = {
  id: "gpuhost:laguna-q5",
  name: "Laguna S 2.1 UD-Q5_K_XL",
  backend: "llama.cpp",
  weights_path: "/home/erikg/models/laguna/UD-Q5_K_XL/Laguna-S-2.1-UD-Q5_K_XL-00001-of-00003.gguf",
  quant: "UD-Q5_K_XL",
  placement: {
    host_id: "gpuhost",
    gpus: [A100_1, A100_2, RTX3090],
    mode: "pipeline",
    vram_req: { [A100_1]: 35840, [A100_2]: 35840, [RTX3090]: 13312 },
    llama_tree: "opt", llama_binary: "/opt/llama.cpp/build/bin/llama-server",
    launch_args: "--n-gpu-layers 999 --ctx-size 65536",
  },
  capability: {
    param_count: null, tool_calling: "unverified", tokens_sec: null, ctx_len: 65536,
    specialties: ["reasoning"], has_vision: false, has_mmproj: false, mmproj_path: null,
  },
  role_tags: ["agent-eligible"],
  enabled: true, notes: null,
};

// ── Observed state helpers ────────────────────────────────────────────────────

function makeObserved(opts: {
  a100_1_used?: number;
  a100_2_used?: number;
  rtx_used?: number;
  running?: Array<{ model_id: string; gpus: string[]; queue_depth?: number }>;
} = {}): HostObservedState[] {
  return [{
    host_id: "gpuhost",
    polled_at: new Date().toISOString(),
    reachable: true,
    gpus: [
      { uuid: A100_1, name: "A100 80GB", index: 0, vram_total_mib: A100_TOTAL, vram_used_mib: opts.a100_1_used ?? 0, util_pct: 0, temp_c: 40, processes: [] },
      { uuid: A100_2, name: "A100 80GB", index: 1, vram_total_mib: A100_TOTAL, vram_used_mib: opts.a100_2_used ?? 0, util_pct: 0, temp_c: 40, processes: [] },
      { uuid: RTX3090, name: "RTX 3090",  index: 2, vram_total_mib: RTX_TOTAL,  vram_used_mib: opts.rtx_used  ?? 0, util_pct: 0, temp_c: 45, processes: [] },
    ],
    running_models: (opts.running ?? []).map((r, i) => ({
      model_id: r.model_id,
      pid: 10000 + i,
      gpus: r.gpus,
      health: "healthy" as const,
      tokens_sec: null,
      queue_depth: r.queue_depth ?? 0,
      started_at: new Date().toISOString(),
    })),
    agent_version: "0.1.0",
  }];
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeAll(() => {
  getDb().prepare("DELETE FROM agent_pool").run();
  upsertModel(NEMOTRON);
  upsertModel(GEMMA4);
  upsertModel(QWEN_CPU);
  upsertModel(LAGUNA);
});

// ── computePreemptionPreview() ────────────────────────────────────────────────

describe("computePreemptionPreview", () => {
  it("throws if model not found", () => {
    expect(() =>
      computePreemptionPreview("gpuhost:does-not-exist", makeObserved())
    ).toThrow("Model not found: gpuhost:does-not-exist");
  });

  it("model fits with nothing running → no victims, no gap", () => {
    const preview = computePreemptionPreview(GEMMA4.id, makeObserved());
    expect(preview.incoming_model_id).toBe(GEMMA4.id);
    expect(preview.victims).toEqual([]);
    expect(preview.requires_gap).toBe(false);
    expect(preview.estimated_gap_sec).toBe(0);
  });

  it("model fits alongside a non-conflicting running model → no victims", () => {
    // NEMOTRON on A100_1; GEMMA4 on RTX3090 — no GPU overlap
    const obs = makeObserved({
      a100_1_used: 34816,
      running: [{ model_id: NEMOTRON.id, gpus: [A100_1] }],
    });
    const preview = computePreemptionPreview(GEMMA4.id, obs);
    expect(preview.victims).toEqual([]);
    expect(preview.requires_gap).toBe(false);
  });

  it("CPU-only model always fits (no GPU constraints)", () => {
    // Even with all GPUs fully loaded
    const obs = makeObserved({
      a100_1_used: A100_TOTAL,
      a100_2_used: A100_TOTAL,
      rtx_used: RTX_TOTAL,
      running: [
        { model_id: NEMOTRON.id, gpus: [A100_1] },
        { model_id: GEMMA4.id,   gpus: [RTX3090] },
      ],
    });
    const preview = computePreemptionPreview(QWEN_CPU.id, obs);
    expect(preview.victims).toEqual([]);
    expect(preview.requires_gap).toBe(false);
  });

  it("model does not fit → identifies minimum victim set", () => {
    // NEMOTRON using A100_1: 34816. LAGUNA needs A100_1: 35840 → requires 35840 free.
    // A100_1 has 81920 - 34816 = 47104 free. 47104 >= 35840 → actually fits!
    // To force eviction: we need A100_1 used = 81920 - 35839 = 46081 MiB used.
    // Use two running models on A100_1: NEMOTRON (34816) + extra usage:
    // Set vram_used directly to force the scenario.
    const obs = makeObserved({
      a100_1_used: 81920 - 10240,  // only 10240 MiB free on A100_1
      a100_2_used: 0,
      rtx_used: 0,
      running: [{ model_id: NEMOTRON.id, gpus: [A100_1] }],
    });
    // LAGUNA needs A100_1: 35840 > 10240 available → eviction needed
    const preview = computePreemptionPreview(LAGUNA.id, obs);
    expect(preview.victims.length).toBeGreaterThan(0);
    expect(preview.victims[0].model_id).toBe(NEMOTRON.id);
    expect(preview.victims[0].gpus_freed).toContain(A100_1);
  });

  it("victim mid_request=true when queue_depth > 0", () => {
    const obs = makeObserved({
      a100_1_used: 81920 - 10240,
      running: [{ model_id: NEMOTRON.id, gpus: [A100_1], queue_depth: 3 }],
    });
    const preview = computePreemptionPreview(LAGUNA.id, obs);
    expect(preview.victims[0].mid_request).toBe(true);
  });

  it("victim mid_request=false when queue_depth = 0", () => {
    const obs = makeObserved({
      a100_1_used: 81920 - 10240,
      running: [{ model_id: NEMOTRON.id, gpus: [A100_1], queue_depth: 0 }],
    });
    const preview = computePreemptionPreview(LAGUNA.id, obs);
    expect(preview.victims[0].mid_request).toBe(false);
  });

  it("victim auto_resume=true when model is in pool with auto_resume", () => {
    getDb().prepare("DELETE FROM agent_pool").run();
    addToAgentPool(NEMOTRON.id, true);
    const obs = makeObserved({
      a100_1_used: 81920 - 10240,
      running: [{ model_id: NEMOTRON.id, gpus: [A100_1] }],
    });
    const preview = computePreemptionPreview(LAGUNA.id, obs);
    expect(preview.victims[0].auto_resume).toBe(true);
    getDb().prepare("DELETE FROM agent_pool").run();
  });

  it("victim auto_resume=false when model is in pool without auto_resume", () => {
    getDb().prepare("DELETE FROM agent_pool").run();
    addToAgentPool(NEMOTRON.id, false);
    const obs = makeObserved({
      a100_1_used: 81920 - 10240,
      running: [{ model_id: NEMOTRON.id, gpus: [A100_1] }],
    });
    const preview = computePreemptionPreview(LAGUNA.id, obs);
    expect(preview.victims[0].auto_resume).toBe(false);
    getDb().prepare("DELETE FROM agent_pool").run();
  });

  it("victim auto_resume=false when model is NOT in pool", () => {
    getDb().prepare("DELETE FROM agent_pool").run();
    const obs = makeObserved({
      a100_1_used: 81920 - 10240,
      running: [{ model_id: NEMOTRON.id, gpus: [A100_1] }],
    });
    const preview = computePreemptionPreview(LAGUNA.id, obs);
    expect(preview.victims[0].auto_resume).toBe(false);
  });

  it("requires_gap=false because GPU total VRAM is sufficient", () => {
    // requires_gap checks if model fits in TOTAL GPU VRAM, ignoring current occupancy.
    // With A100_1 total=81920 and LAGUNA needing A100_1=35840, requires_gap is always false
    // for any model in our registry (no model needs > GPU total).
    const obs = makeObserved({
      a100_1_used: 81920 - 10240,
      running: [{ model_id: NEMOTRON.id, gpus: [A100_1] }],
    });
    const preview = computePreemptionPreview(LAGUNA.id, obs);
    expect(preview.requires_gap).toBe(false);
    expect(preview.estimated_gap_sec).toBe(0);
  });

  it("blocked_after includes models that share GPU with incoming", () => {
    // GEMMA4 (RTX3090 only) is blocked by LAGUNA (uses RTX3090 among others)
    const obs = makeObserved({});
    const preview = computePreemptionPreview(LAGUNA.id, obs);
    const blockedIds = preview.blocked_after.map((b) => b.model_id);
    // GEMMA4 uses RTX3090, LAGUNA also uses RTX3090 → GEMMA4 is blocked
    expect(blockedIds).toContain(GEMMA4.id);
    // NEMOTRON uses A100_1, LAGUNA uses A100_1 → NEMOTRON is blocked
    expect(blockedIds).toContain(NEMOTRON.id);
  });

  it("blocked_after excludes already-running models", () => {
    // If GEMMA4 is already running, it should NOT appear in blocked_after
    const obs = makeObserved({
      rtx_used: 8192,
      running: [{ model_id: GEMMA4.id, gpus: [RTX3090] }],
    });
    const preview = computePreemptionPreview(LAGUNA.id, obs);
    const blockedIds = preview.blocked_after.map((b) => b.model_id);
    expect(blockedIds).not.toContain(GEMMA4.id);
  });
});

// ── computeBlocked() ─────────────────────────────────────────────────────────

describe("computeBlocked", () => {
  it("model not found → empty array", () => {
    const blocked = computeBlocked("gpuhost:nonexistent", makeObserved());
    expect(blocked).toEqual([]);
  });

  it("no GPU conflicts → empty blocked list", () => {
    // GEMMA4 (RTX3090) and QWEN_CPU (no GPUs) — QWEN_CPU blocks nothing
    const blocked = computeBlocked(QWEN_CPU.id, makeObserved());
    // CPU model has no GPUs, so no conflicts
    expect(blocked).toEqual([]);
  });

  it("NEMOTRON on A100_1 blocks LAGUNA (which also needs A100_1)", () => {
    const blocked = computeBlocked(NEMOTRON.id, makeObserved());
    const blockedIds = blocked.map((b) => b.model_id);
    expect(blockedIds).toContain(LAGUNA.id);
  });

  it("blocked entry has correct blocked_gpus", () => {
    const blocked = computeBlocked(NEMOTRON.id, makeObserved());
    const lagunaBlocked = blocked.find((b) => b.model_id === LAGUNA.id);
    expect(lagunaBlocked).toBeDefined();
    expect(lagunaBlocked!.blocked_gpus).toContain(A100_1);
    expect(lagunaBlocked!.blocked_by_model_id).toBe(NEMOTRON.id);
  });

  it("already-running model is not included in blocked", () => {
    // LAGUNA is already running; computeBlocked(NEMOTRON) should not include it
    const obs = makeObserved({
      a100_1_used: 81920,
      a100_2_used: 81920,
      rtx_used: RTX_TOTAL,
      running: [{ model_id: LAGUNA.id, gpus: [A100_1, A100_2, RTX3090] }],
    });
    const blocked = computeBlocked(NEMOTRON.id, obs);
    const blockedIds = blocked.map((b) => b.model_id);
    expect(blockedIds).not.toContain(LAGUNA.id);
  });

  it("LAGUNA (all three GPUs) blocks NEMOTRON, GEMMA4, and itself is not blocked by self", () => {
    const blocked = computeBlocked(LAGUNA.id, makeObserved());
    const blockedIds = blocked.map((b) => b.model_id);
    // LAGUNA itself is excluded
    expect(blockedIds).not.toContain(LAGUNA.id);
    // NEMOTRON (A100_1) is blocked
    expect(blockedIds).toContain(NEMOTRON.id);
    // GEMMA4 (RTX3090) is blocked
    expect(blockedIds).toContain(GEMMA4.id);
    // QWEN_CPU (no GPUs) is NOT blocked
    expect(blockedIds).not.toContain(QWEN_CPU.id);
  });
});
