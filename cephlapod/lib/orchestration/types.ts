/**
 * Orchestration system — shared TypeScript types.
 * Single source of truth; API routes, UI, and reconciler all import from here.
 */

// ── Hardware ──────────────────────────────────────────────────────────────────

export type PlacementMode =
  | "single"        // one GPU, all layers on-device
  | "pipeline"      // layers split across 2-3 GPUs (heterogeneous ok)
  | "layer-split"   // explicit layer-range assignment per GPU UUID
  | "gpu-cpu-moe"   // GPUs hold dense/active experts; CPU RAM holds inactive experts
  | "cpu";          // pure CPU — only for MoE models that fit entirely in DDR5

export interface GpuProcess {
  pid: number;
  model_id: string | null; // null = foreign (not dashboard-managed)
  vram_mib: number;
  is_foreign: boolean;
  command: string;
}

export interface GpuState {
  uuid: string;
  name: string;
  index: number;
  vram_total_mib: number;
  vram_used_mib: number;
  util_pct: number;
  temp_c: number;
  processes: GpuProcess[];
}

export interface RunningModel {
  model_id: string;
  pid: number;
  gpus: string[]; // UUIDs
  health: "healthy" | "degraded" | "unreachable";
  tokens_sec: number | null;
  queue_depth: number | null;
  started_at: string;
}

export interface HostObservedState {
  host_id: string;
  polled_at: string;
  reachable: boolean;
  gpus: GpuState[];
  running_models: RunningModel[];
  agent_version: string | null;
}

// ── Model Registry ────────────────────────────────────────────────────────────

export type ToolCalling = "verified" | "unverified" | "known-broken";
export type LlamaTree =
  | "system"           // /usr/local/bin/llama-server
  | "mainline"         // ~/src/mainline-llama.cpp/build/bin/llama-server
  | "glm5next"         // ~/src/glm5next-llama.cpp/build/bin/llama-server
  | "qwen4mtp"         // ~/src/qwen4mtp-llama.cpp/build/bin/llama-server
  | "opt"              // /opt/llama.cpp/build/bin/llama-server
  | "llama-swap";      // managed by llama-swap, no direct binary

export type ModelSpecialty =
  | "code"
  | "reasoning"
  | "summarization"
  | "vision"
  | "embedding"
  | "stt"
  | "tts"
  | "video-gen"
  | "function-calling"
  | "mtp-draft";

export interface VramRequirement {
  [gpu_uuid: string]: number; // MiB per GPU UUID
}

export interface LayerSplit {
  [gpu_uuid: string]: string; // e.g. "0-39"
}

export interface ModelPlacement {
  host_id: string;
  gpus: string[];        // GPU UUIDs (empty = CPU-only)
  mode: PlacementMode;
  layer_split?: LayerSplit;
  vram_req: VramRequirement;
  llama_tree: LlamaTree;
  llama_binary: string;  // absolute path to llama-server binary
  launch_args: string;   // args after the binary (model path, ctx, etc.)
}

export interface ModelCapability {
  param_count: string | null;       // e.g. "27B", "350M"
  tool_calling: ToolCalling;
  tokens_sec: number | null;        // last measured
  ctx_len: number | null;
  specialties: ModelSpecialty[];
  has_vision: boolean;
  has_mmproj: boolean;
  mmproj_path: string | null;
}

export interface Model {
  id: string;
  name: string;
  backend: "llama.cpp" | "llama-swap" | "whisper.cpp" | "other";
  weights_path: string;
  quant: string | null;
  placement: ModelPlacement;
  capability: ModelCapability;
  role_tags: ("orchestrator-eligible" | "agent-eligible")[];
  enabled: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// Warnings computed at save time, not stored
export interface ModelWarning {
  code: "no-tool-calling" | "ctx-too-small" | "placement-conflict" | "binary-missing" | "vram-exceeds-gpu";
  message: string;
  severity: "warn" | "block";
}

// ── Desired State ─────────────────────────────────────────────────────────────

export interface OrchestratorSlot {
  model_id: string | null;
  set_at: string;
  set_by: string;
}

export interface AgentPoolEntry {
  model_id: string;
  added_at: string;
  auto_resume: boolean;
}

// ── Preemption ────────────────────────────────────────────────────────────────

export interface PreemptionVictim {
  model_id: string;
  model_name: string;
  gpus_freed: string[];   // UUIDs
  mid_request: boolean;   // true if currently serving a request
  auto_resume: boolean;
}

export interface PreemptionPreview {
  incoming_model_id: string;
  victims: PreemptionVictim[];
  requires_gap: boolean;       // true when VRAM doesn't allow load-then-switch
  estimated_gap_sec: number;
  blocked_after: BlockedEntry[]; // models blocked by the new placement
}

export interface BlockedEntry {
  model_id: string;
  model_name: string;
  blocked_by_model_id: string;
  blocked_gpus: string[]; // UUIDs held by blocker
}

// ── Reconciler ────────────────────────────────────────────────────────────────

export type ReconcilerAction =
  | { type: "start"; model_id: string }
  | { type: "stop"; model_id: string; reason: string }
  | { type: "cutover-orchestrator"; from: string | null; to: string }
  | { type: "restore"; model_id: string; reason: "auto-resume" };

export interface ReconcilerState {
  frozen: boolean;
  last_run: string | null;
  last_error: string | null;
  pending_actions: ReconcilerAction[];
  transition_count_last_minute: number;
}

// ── Routing Log ───────────────────────────────────────────────────────────────

export type RoutingOutcome = "success" | "timeout" | "repaired" | "error" | "passthrough";

export interface RoutingLogEntry {
  id: number;
  ts: string;
  session_id: string;
  prompt_summary: string | null;
  orchestrator_model_id: string | null;
  agent_model_id: string | null;
  routing_reason: string | null;
  latency_plan_ms: number | null;
  latency_agent_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  outcome: RoutingOutcome;
  error_detail: string | null;
  // full_transcript fetched separately (can be large)
}

// ── Shim / Claude Code endpoint ───────────────────────────────────────────────

export interface ShimSession {
  id: string;
  connected_at: string;
  last_seen: string;
  client_ip: string;
  passthrough: boolean;
  request_count: number;
}

export interface ShimConfig {
  endpoint_url: string;      // e.g. http://localhost:4000
  auth_token: string;
  model_string: string;      // what to tell Claude Code to use as model name
}
