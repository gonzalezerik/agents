/**
 * Seed data for the model registry.
 * Run once on first boot or via `npm run seed-models`.
 * Idempotent — uses upsertModel, safe to re-run.
 */

import { upsertModel } from "./model-registry";
import type { Model } from "./types";

// ── GPU UUIDs (gpuhost) ──────────────────────────────────────────────────────
const A100_1  = "GPU-a1000001-0000-0000-0000-000000000000"; // A100 SXM4 40GB
const A100_2  = "GPU-a1000002-0000-0000-0000-000000000000"; // A100 SXM4 40GB
const RTX3090 = "GPU-30900001-0000-0000-0000-000000000000"; // RTX 3090 24GB

// ── GPU UUID (llmhost-llm / proxmox passthrough) ──────────────────────────────
const RTX_PRO = "GPU-c0000004-0000-0000-0000-000000000000"; // RTX PRO 4000 24GB

// ── llama-server binary paths (gpuhost) ─────────────────────────────────────
const BIN_OPT      = "/opt/llama.cpp/build/bin/llama-server";
const BIN_MAINLINE = "/home/erikg/src/mainline-llama.cpp/build/bin/llama-server";
const BIN_GLM5NEXT = "/home/erikg/src/glm5next-llama.cpp/build/bin/llama-server";
const BIN_QWEN4MTP = "/home/erikg/src/qwen4mtp-llama.cpp/build/bin/llama-server";
const BIN_SYSTEM   = "/usr/local/bin/llama-server";

const now = new Date().toISOString();

type SeedModel = Omit<Model, "created_at" | "updated_at">;

// ── helpers ───────────────────────────────────────────────────────────────────

function mib(gb: number) { return Math.round(gb * 1024); }

// Standard flash-attn flags used across most GPU models
const FA = "--flash-attn on --cache-type-k q8_0 --cache-type-v q8_0";

// ── GPUHOST — tiny / embedding ───────────────────────────────────────────────

const GPUHOST_TINY: SeedModel[] = [
  {
    id: "gpuhost:embeddinggemma-300m",
    name: "EmbeddingGemma 300M",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/embeddinggemma-300m/embeddinggemma-300M-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(0.4) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 8192 --embedding " + FA,
    },
    capability: {
      param_count: "300M", tool_calling: "known-broken",
      tokens_sec: null, ctx_len: 8192,
      specialties: ["embedding"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: [],
    enabled: true, notes: null,
  },
  {
    id: "gpuhost:functiongemma-270m",
    name: "FunctionGemma 270M",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/functiongemma-270m/functiongemma-270m-it-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(0.4) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 8192 " + FA,
    },
    capability: {
      param_count: "270M", tool_calling: "verified",
      tokens_sec: null, ctx_len: 8192,
      specialties: ["function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: [],
    enabled: true, notes: "Lightweight function-call dispatcher",
  },
  {
    id: "gpuhost:granite-350m-q8",
    name: "Granite 4.0 350M (Q8_0)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/granite-350m/granite-4.0-h-350m-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(0.5) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 16384 " + FA,
    },
    capability: {
      param_count: "350M", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 16384,
      specialties: ["code", "summarization"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: [],
    enabled: true, notes: null,
  },
  {
    id: "gpuhost:granite-350m-q8xl",
    name: "Granite 4.0 350M (UD-Q8_K_XL)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/granite-350m/granite-4.0-h-350m-UD-Q8_K_XL.gguf",
    quant: "UD-Q8_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(0.5) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 16384 " + FA,
    },
    capability: {
      param_count: "350M", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 16384,
      specialties: ["code", "summarization"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: [],
    enabled: false, notes: "Higher-fidelity quant; prefer q8 for speed",
  },
  {
    id: "gpuhost:whisper-large-v3",
    name: "Whisper Large v3",
    backend: "whisper.cpp",
    weights_path: "/home/erikg/models/whisper-large-v3/whisper-large-v3.bin",
    quant: null,
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(3) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999",
    },
    capability: {
      param_count: "1.5B", tool_calling: "known-broken",
      tokens_sec: null, ctx_len: null,
      specialties: ["stt"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: [],
    enabled: true, notes: "whisper.cpp binary, not llama-server",
  },
  {
    id: "gpuhost:orpheus-3b",
    name: "Orpheus 3B TTS",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/orpheus-3b/orpheus-3b-0.1-ft-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(3.5) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 8192 " + FA,
    },
    capability: {
      param_count: "3B", tool_calling: "known-broken",
      tokens_sec: null, ctx_len: 8192,
      specialties: ["tts"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: [],
    enabled: true, notes: null,
  },
  {
    id: "gpuhost:qwen25-coder-1.5b",
    name: "Qwen 2.5 Coder 1.5B",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen25-coder-1.5b/Qwen2.5-Coder-1.5B-Instruct-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(2) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 32768 " + FA,
    },
    capability: {
      param_count: "1.5B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 32768,
      specialties: ["code"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "Fast code completion / fill-in-middle",
  },
];

// ── GPUHOST — small vision / multimodal (RTX 3090) ──────────────────────────

const GPUHOST_SMALL_VISION: SeedModel[] = [
  {
    id: "gpuhost:qwen35-4b",
    name: "Qwen 3.5 4B (RTX 3090)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen35-4b/Qwen3.5-4B-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(4) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 32768 --jinja " + FA +
        " --mmproj /home/erikg/models/qwen35-4b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "4B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 32768,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/home/erikg/models/qwen35-4b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "201-language support; thinking + non-thinking mode",
  },
  {
    id: "gpuhost:gemma4-e4b",
    name: "Gemma 4 E4B (RTX 3090)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/gemma4-e4b/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(6) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 131072 --jinja " + FA +
        " --mmproj /home/erikg/models/gemma4-e4b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "4B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/home/erikg/models/gemma4-e4b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "Native audio input (wav/mp3/m4a/flac/webm); QAT quant",
  },
  {
    id: "gpuhost:qwen3vl-8b",
    name: "Qwen3 VL 8B (RTX 3090)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3vl-8b/Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(7) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 8192 --jinja " + FA +
        " --mmproj /home/erikg/models/qwen3vl-8b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "8B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 8192,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/home/erikg/models/qwen3vl-8b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: null,
  },
  {
    id: "gpuhost:gemma4-12b",
    name: "Gemma 4 12B (RTX 3090)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/gemma4-12b/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(8) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 262144 --jinja " + FA +
        " --mmproj /home/erikg/models/gemma4-12b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "12B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 262144,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/home/erikg/models/gemma4-12b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "Translation + multimodal; QAT quant",
  },
  {
    id: "gpuhost:qwen35-9b",
    name: "Qwen 3.5 9B (RTX 3090)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen35-9b/Qwen3.5-9B-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(8) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 32768 --jinja " + FA +
        " --mmproj /home/erikg/models/qwen35-9b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "9B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 32768,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/home/erikg/models/qwen35-9b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: null,
  },
  {
    id: "gpuhost:ministral-3-8b",
    name: "Ministral 3 8B",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/ministral-3-8b/Ministral-3-8B-Instruct-2512-UD-Q8_K_XL.gguf",
    quant: "UD-Q8_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(12) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 32768 " + FA,
    },
    capability: {
      param_count: "8B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 32768,
      specialties: ["code", "summarization"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: null,
  },
  {
    id: "gpuhost:ornith-9b",
    name: "Ornith 1.5 9B",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/ornith-9b/Ornith-1.5-9B-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(10) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 32768 " + FA,
    },
    capability: {
      param_count: "9B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 32768,
      specialties: ["summarization"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: null,
  },
  {
    id: "gpuhost:gemma4-26b",
    name: "Gemma 4 26B A4B",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/gemma4-26b/gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(16) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 131072 --jinja " + FA +
        " --mmproj /home/erikg/models/gemma4-26b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "26B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["vision", "reasoning"], has_vision: true, has_mmproj: true,
      mmproj_path: "/home/erikg/models/gemma4-26b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "MoE A4B (4B active), QAT quant; fits in 3090 VRAM",
  },
];

// ── GPUHOST — single A100 models ─────────────────────────────────────────────

const GPUHOST_SINGLE_A100: SeedModel[] = [
  {
    id: "gpuhost:minimax-h3-fl2va",
    name: "MiniMax H3 FL2VA (Q8_0)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/minimax-h3/minimax_h3_fl2va_pruned-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [A100_1], mode: "single",
      vram_req: { [A100_1]: mib(21) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 65536 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["vision"], has_vision: true, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "H3 (linear-attention hybrid); FL2VA pruned vision variant",
  },
  {
    id: "gpuhost:minimax-h3-qwen3vl",
    name: "MiniMax H3 Qwen3-VL 32B (Q4_K_M)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/minimax-h3/qwen3vl_32b_minimax_h3-Q4_K_M.gguf",
    quant: "Q4_K_M",
    placement: {
      host_id: "gpuhost", gpus: [A100_1], mode: "single",
      vram_req: { [A100_1]: mib(18) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 32768 --jinja " + FA,
    },
    capability: {
      param_count: "32B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 32768,
      specialties: ["vision"], has_vision: true, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "Qwen3-VL 32B fused with MiniMax H3 architecture",
  },
  {
    id: "gpuhost:muse-glimmer",
    name: "Muse Glimmer 30B",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/muse-glimmer/Muse-Glimmer-30B-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [A100_1], mode: "single",
      vram_req: { [A100_1]: mib(32) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 32768 --jinja " + FA +
        " --mmproj /home/erikg/models/muse-glimmer/mmproj-Muse-Glimmer-30B-Q8_0.gguf",
    },
    capability: {
      param_count: "30B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 32768,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/home/erikg/models/muse-glimmer/mmproj-Muse-Glimmer-30B-Q8_0.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: null,
  },
  {
    id: "gpuhost:nemotron-lightning",
    name: "Nemotron Lightning 30B A3B",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/nemotron-lightning/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [A100_1], mode: "single",
      vram_req: { [A100_1]: mib(34) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 131072 " + FA,
    },
    capability: {
      param_count: "30B", tool_calling: "verified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "MoE A3B; NVIDIA-tuned for tool calling",
  },
  {
    id: "gpuhost:ornith-35b",
    name: "Ornith 1.5 35B A3B",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/ornith-35b/Ornith-1.5-35B-A3B-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [A100_1], mode: "single",
      vram_req: { [A100_1]: mib(36) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 131072 " + FA,
    },
    capability: {
      param_count: "35B", tool_calling: "verified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "MoE A3B",
  },
  {
    id: "gpuhost:qwen3.6-35b-a3b-gpu",
    name: "Qwen 3.6 35B A3B Q8 (A100 GPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.6-35b-a3b-gguf/Qwen3.6-35B-A3B-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [A100_1], mode: "single",
      vram_req: { [A100_1]: mib(36) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 131072 " + FA,
    },
    capability: {
      param_count: "35B", tool_calling: "verified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "function-calling", "code"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "GPU variant; see qwen3.6-35b-a3b-cpu for DDR5-only",
  },
  {
    id: "gpuhost:qwen3.6-35b-a3b-cpu",
    name: "Qwen 3.6 35B A3B Q8 (CPU-only, port 8004)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.6-35b-a3b-gguf/Qwen3.6-35B-A3B-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [], mode: "cpu",
      vram_req: {},
      llama_tree: "system", llama_binary: BIN_SYSTEM,
      launch_args: "--n-gpu-layers 0 --ctx-size 131072 --threads 32",
    },
    capability: {
      param_count: "35B", tool_calling: "verified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "function-calling", "code"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "35GB fits in 61GB DDR5; managed by llama-q35b-cpu.service on port 8004; CUDA_VISIBLE_DEVICES=''",
  },
  {
    id: "gpuhost:qwen3.8-27b-q4",
    name: "Qwen 3.8 27B UD-Q4_K_XL",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.8-27b-gguf/Qwen3.8-27B-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(18) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      launch_args: "--n-gpu-layers 999 --ctx-size 131072 " + FA,
    },
    capability: {
      param_count: "27B", tool_calling: "verified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "Qwen3.8 architecture (qwen4exp branch); SSM/linear hybrid attention",
  },
  {
    id: "gpuhost:qwen3.8-27b-q8",
    name: "Qwen 3.8 27B UD-Q8_K_XL",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.8-27b-gguf/Qwen3.8-27B-UD-Q8_K_XL.gguf",
    quant: "UD-Q8_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1], mode: "single",
      vram_req: { [A100_1]: mib(30) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      launch_args: "--n-gpu-layers 999 --ctx-size 131072 " + FA,
    },
    capability: {
      param_count: "27B", tool_calling: "verified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "Higher-fidelity; uses A100 due to 30GB size",
  },
];

// ── GPUHOST — dual A100 models (pipeline, 80GB combined) ─────────────────────

const GPUHOST_DUAL_A100: SeedModel[] = [
  {
    id: "gpuhost:qwen3-coder-next",
    name: "Qwen3 Coder Next Q8_0",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3-coder-next/Q8_0/Qwen3-Coder-Next-Q8_0-00001-of-00003.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2], mode: "pipeline",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(39) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      launch_args: "--n-gpu-layers 999 --ctx-size 65536 --tensor-split 40,40 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "verified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["code", "reasoning", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "79GB; split evenly across both A100s",
  },
];

// ── GPUHOST — all-3-GPU models (A100×2 + RTX 3090, 104GB combined) ───────────

const GPUHOST_ALL_GPU: SeedModel[] = [
  {
    id: "gpuhost:laguna-q5",
    name: "Laguna S 2.1 UD-Q5_K_XL",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/laguna/UD-Q5_K_XL/Laguna-S-2.1-UD-Q5_K_XL-00001-of-00003.gguf",
    quant: "UD-Q5_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2, RTX3090], mode: "pipeline",
      vram_req: { [A100_1]: mib(35), [A100_2]: mib(35), [RTX3090]: mib(13) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 65536 --tensor-split 35,35,13 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["reasoning"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "83GB; Laguna-S 2.1 DFlash architecture",
  },
  {
    id: "gpuhost:laguna-bf16",
    name: "Laguna S 2.1 BF16 (tiny variant)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/laguna/laguna-s-2.1-DFlash-BF16.gguf",
    quant: "BF16",
    placement: {
      host_id: "gpuhost", gpus: [RTX3090], mode: "single",
      vram_req: { [RTX3090]: mib(3) },
      llama_tree: "opt", llama_binary: BIN_OPT,
      launch_args: "--n-gpu-layers 999 --ctx-size 8192 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 8192,
      specialties: [], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: [],
    enabled: true, notes: "2.1GB small variant; full Q5_K_XL is gpuhost:laguna-q5",
  },
  {
    id: "gpuhost:step",
    name: "Step 3.7 Flash UD-Q3_K_XL",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/step/UD-Q3_K_XL/Step-3.7-Flash-UD-Q3_K_XL-00001-of-00003.gguf",
    quant: "UD-Q3_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2, RTX3090], mode: "pipeline",
      vram_req: { [A100_1]: mib(34), [A100_2]: mib(34), [RTX3090]: mib(19) },
      llama_tree: "qwen4mtp", llama_binary: BIN_QWEN4MTP,
      launch_args: "--n-gpu-layers 999 --ctx-size 65536 --tensor-split 34,34,19 " + FA +
        " --mmproj /home/erikg/models/step/mmproj-F16.gguf",
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["vision", "mtp-draft", "reasoning"], has_vision: true, has_mmproj: true,
      mmproj_path: "/home/erikg/models/step/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "~87GB with mmproj; use qwen4mtp tree for MTP draft support",
  },
  {
    id: "gpuhost:step-mtp",
    name: "Step 3.7 Flash MTP Draft (Q8_0)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/step/Step3.7-flash-mtp-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [A100_1], mode: "single",
      vram_req: { [A100_1]: mib(4) },
      llama_tree: "qwen4mtp", llama_binary: BIN_QWEN4MTP,
      launch_args: "--n-gpu-layers 999 --ctx-size 4096 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "known-broken",
      tokens_sec: null, ctx_len: 4096,
      specialties: ["mtp-draft"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: [],
    enabled: true, notes: "Speculative-decoding draft model for gpuhost:step; load on A100 alongside main model",
  },
];

// ── GPUHOST — large MoE: all 3 GPUs + CPU offload ───────────────────────────

const GPUHOST_ALL_GPU_CPU_MOE: SeedModel[] = [
  {
    id: "gpuhost:glm-5.3-flash-iq3xxs-all",
    name: "GLM 5.3 Flash UD-IQ3_XXS (all GPUs + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/glm-5.3-flash-gguf/UD-IQ3_XXS/GLM-5.3-Flash-UD-IQ3_XXS-00001-of-00004.gguf",
    quant: "UD-IQ3_XXS",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2, RTX3090], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40), [RTX3090]: mib(24) },
      llama_tree: "glm5next", llama_binary: BIN_GLM5NEXT,
      // 104GB GPU + ~9GB CPU overflow for inactive MoE experts
      launch_args: "--n-gpu-layers 62 --ctx-size 131072 --tensor-split 40,40,24 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "code"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "113GB; 9GB expert overflow to CPU DDR5; uses glm5next tree",
  },
  {
    id: "gpuhost:glm-5.3-flash-q2kxl-all",
    name: "GLM 5.3 Flash UD-Q2_K_XL (all GPUs + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/glm-5.3-flash-gguf/UD-Q2_K_XL/GLM-5.3-Flash-UD-Q2_K_XL-00001-of-00004.gguf",
    quant: "UD-Q2_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2, RTX3090], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40), [RTX3090]: mib(22) },
      llama_tree: "glm5next", llama_binary: BIN_GLM5NEXT,
      launch_args: "--n-gpu-layers 62 --ctx-size 131072 --tensor-split 40,40,22 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "code"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "102GB; mostly fits on GPU with small CPU buffer for MoE spill",
  },
  {
    id: "gpuhost:deepseek-v4-flash-vision-iq2xxs-all",
    name: "DeepSeek V4 Flash Vision UD-IQ2_XXS (all GPUs + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/deepseek-v4-flash-vision-exp-gguf/UD-IQ2_XXS/DeepSeek-V4-Flash-Vision-Exp-UD-IQ2_XXS-00001-of-00003.gguf",
    quant: "UD-IQ2_XXS",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2, RTX3090], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(35), [A100_2]: mib(35), [RTX3090]: mib(15) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      launch_args: "--n-gpu-layers 999 --ctx-size 65536 --tensor-split 35,35,15 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["vision", "reasoning"], has_vision: true, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "85GB; vision-exp variant",
  },
  {
    id: "gpuhost:deepseek-v4-flash-vision-iq3xxs-all",
    name: "DeepSeek V4 Flash Vision UD-IQ3_XXS (all GPUs + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/deepseek-v4-flash-vision-exp-gguf/UD-IQ3_XXS/DeepSeek-V4-Flash-Vision-Exp-UD-IQ3_XXS-00001-of-00004.gguf",
    quant: "UD-IQ3_XXS",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2, RTX3090], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(38), [A100_2]: mib(38), [RTX3090]: mib(20) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      launch_args: "--n-gpu-layers 999 --ctx-size 65536 --tensor-split 38,38,20 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["vision", "reasoning"], has_vision: true, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "96GB; fits within 104GB GPU VRAM with small CPU buffer",
  },
  {
    id: "gpuhost:deepseek-v4-flash-vision-q3kxl-all",
    name: "DeepSeek V4 Flash Vision UD-Q3_K_XL (all GPUs + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/deepseek-v4-flash-vision-exp-gguf/UD-Q3_K_XL/DeepSeek-V4-Flash-Vision-Exp-UD-Q3_K_XL-00001-of-00004.gguf",
    quant: "UD-Q3_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2, RTX3090], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40), [RTX3090]: mib(24) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      // 120GB total; ~16GB expert overflow to CPU
      launch_args: "--n-gpu-layers 56 --ctx-size 65536 --tensor-split 40,40,24 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["vision", "reasoning"], has_vision: true, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "120GB; 16GB expert overflow to CPU; highest quality vision quant",
  },
  {
    id: "gpuhost:qwen3.8-flash-next-iq4xs-all",
    name: "Qwen 3.8 Flash Next UD-IQ4_XS (all GPUs + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.8-flash-next-gguf/UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf",
    quant: "UD-IQ4_XS",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2, RTX3090], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(36), [A100_2]: mib(36), [RTX3090]: mib(16) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      launch_args: "--n-gpu-layers 999 --ctx-size 65536 --tensor-split 36,36,16 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "verified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["reasoning", "code", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "88GB; fits in GPU VRAM with buffer",
  },
  {
    id: "gpuhost:qwen3.8-flash-next-q3kxl-all",
    name: "Qwen 3.8 Flash Next UD-Q3_K_XL (all GPUs + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.8-flash-next-gguf/UD-Q3_K_XL/Qwen3.8-Flash-Next-UD-Q3_K_XL-00001-of-00003.gguf",
    quant: "UD-Q3_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2, RTX3090], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(34), [A100_2]: mib(34), [RTX3090]: mib(16) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      launch_args: "--n-gpu-layers 999 --ctx-size 65536 --tensor-split 34,34,16 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "verified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["reasoning", "code", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "84GB",
  },
  {
    id: "gpuhost:qwen3.8-flash-next-q4kxl-all",
    name: "Qwen 3.8 Flash Next UD-Q4_K_XL (all GPUs + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.8-flash-next-gguf/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00003.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2, RTX3090], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40), [RTX3090]: mib(24) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      // 104GB exactly fills all GPU VRAM; tiny CPU buffer for MoE experts
      launch_args: "--n-gpu-layers 56 --ctx-size 65536 --tensor-split 40,40,24 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "verified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["reasoning", "code", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "104GB; maxes all 3 GPU VRAM; highest quality quant",
  },
  {
    id: "gpuhost:qwen3.8-flash-next-mtp",
    name: "Qwen 3.8 Flash Next MTP Draft (Q8_0)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.8-flash-next-mtp/MTP/mtp-Qwen3.8-Flash-Next-Q8_0.gguf",
    quant: "Q8_0",
    placement: {
      host_id: "gpuhost", gpus: [A100_1], mode: "single",
      vram_req: { [A100_1]: mib(4) },
      llama_tree: "qwen4mtp", llama_binary: BIN_QWEN4MTP,
      launch_args: "--n-gpu-layers 999 --ctx-size 4096 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "known-broken",
      tokens_sec: null, ctx_len: 4096,
      specialties: ["mtp-draft"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: [],
    enabled: true, notes: "Speculative-decoding draft for qwen3.8-flash-next-*; co-load on A100",
  },
];

// ── GPUHOST — large MoE: dual A100 + CPU offload (3090 stays free) ───────────

const GPUHOST_DUAL_A100_CPU_MOE: SeedModel[] = [
  {
    id: "gpuhost:glm-5.3-flash-iq3xxs-a100",
    name: "GLM 5.3 Flash UD-IQ3_XXS (dual A100 + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/glm-5.3-flash-gguf/UD-IQ3_XXS/GLM-5.3-Flash-UD-IQ3_XXS-00001-of-00004.gguf",
    quant: "UD-IQ3_XXS",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40) },
      llama_tree: "glm5next", llama_binary: BIN_GLM5NEXT,
      // 80GB on GPU + 33GB inactive MoE experts in CPU DDR5
      launch_args: "--n-gpu-layers 44 --ctx-size 131072 --tensor-split 40,40 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "code"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "113GB; 33GB to CPU; RTX 3090 stays free for concurrent model",
  },
  {
    id: "gpuhost:glm-5.3-flash-q2kxl-a100",
    name: "GLM 5.3 Flash UD-Q2_K_XL (dual A100 + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/glm-5.3-flash-gguf/UD-Q2_K_XL/GLM-5.3-Flash-UD-Q2_K_XL-00001-of-00004.gguf",
    quant: "UD-Q2_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40) },
      llama_tree: "glm5next", llama_binary: BIN_GLM5NEXT,
      // 80GB on GPU + 22GB in CPU DDR5
      launch_args: "--n-gpu-layers 44 --ctx-size 131072 --tensor-split 40,40 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "code"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "102GB; 22GB to CPU; RTX 3090 stays free",
  },
  {
    id: "gpuhost:deepseek-v4-flash-vision-iq2xxs-a100",
    name: "DeepSeek V4 Flash Vision UD-IQ2_XXS (dual A100 + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/deepseek-v4-flash-vision-exp-gguf/UD-IQ2_XXS/DeepSeek-V4-Flash-Vision-Exp-UD-IQ2_XXS-00001-of-00003.gguf",
    quant: "UD-IQ2_XXS",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      // 80GB on GPU + 5GB in CPU DDR5; slim overflow
      launch_args: "--n-gpu-layers 56 --ctx-size 65536 --tensor-split 40,40 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["vision", "reasoning"], has_vision: true, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "85GB; RTX 3090 stays free",
  },
  {
    id: "gpuhost:deepseek-v4-flash-vision-iq3xxs-a100",
    name: "DeepSeek V4 Flash Vision UD-IQ3_XXS (dual A100 + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/deepseek-v4-flash-vision-exp-gguf/UD-IQ3_XXS/DeepSeek-V4-Flash-Vision-Exp-UD-IQ3_XXS-00001-of-00004.gguf",
    quant: "UD-IQ3_XXS",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      // 96GB total; 16GB to CPU
      launch_args: "--n-gpu-layers 50 --ctx-size 65536 --tensor-split 40,40 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["vision", "reasoning"], has_vision: true, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "96GB; 16GB to CPU; RTX 3090 stays free",
  },
  {
    id: "gpuhost:deepseek-v4-flash-vision-q3kxl-a100",
    name: "DeepSeek V4 Flash Vision UD-Q3_K_XL (dual A100 + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/deepseek-v4-flash-vision-exp-gguf/UD-Q3_K_XL/DeepSeek-V4-Flash-Vision-Exp-UD-Q3_K_XL-00001-of-00004.gguf",
    quant: "UD-Q3_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      // 120GB total; 40GB to CPU
      launch_args: "--n-gpu-layers 42 --ctx-size 65536 --tensor-split 40,40 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["vision", "reasoning"], has_vision: true, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "120GB; 40GB to CPU; RTX 3090 stays free",
  },
  {
    id: "gpuhost:qwen3.8-flash-next-iq4xs-a100",
    name: "Qwen 3.8 Flash Next UD-IQ4_XS (dual A100 + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.8-flash-next-gguf/UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf",
    quant: "UD-IQ4_XS",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      // 88GB; 8GB to CPU
      launch_args: "--n-gpu-layers 54 --ctx-size 65536 --tensor-split 40,40 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "verified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["reasoning", "code", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "88GB; 8GB to CPU; RTX 3090 stays free",
  },
  {
    id: "gpuhost:qwen3.8-flash-next-q3kxl-a100",
    name: "Qwen 3.8 Flash Next UD-Q3_K_XL (dual A100 + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.8-flash-next-gguf/UD-Q3_K_XL/Qwen3.8-Flash-Next-UD-Q3_K_XL-00001-of-00003.gguf",
    quant: "UD-Q3_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      // 84GB; 4GB to CPU
      launch_args: "--n-gpu-layers 56 --ctx-size 65536 --tensor-split 40,40 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "verified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["reasoning", "code", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "84GB; 4GB to CPU; RTX 3090 stays free",
  },
  {
    id: "gpuhost:qwen3.8-flash-next-q4kxl-a100",
    name: "Qwen 3.8 Flash Next UD-Q4_K_XL (dual A100 + CPU)",
    backend: "llama.cpp",
    weights_path: "/home/erikg/models/qwen3.8-flash-next-gguf/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00003.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "gpuhost", gpus: [A100_1, A100_2], mode: "gpu-cpu-moe",
      vram_req: { [A100_1]: mib(40), [A100_2]: mib(40) },
      llama_tree: "mainline", llama_binary: BIN_MAINLINE,
      // 104GB; 24GB to CPU
      launch_args: "--n-gpu-layers 44 --ctx-size 65536 --tensor-split 40,40 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "verified",
      tokens_sec: null, ctx_len: 65536,
      specialties: ["reasoning", "code", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "104GB; 24GB to CPU; RTX 3090 stays free for concurrent model",
  },
];

// ── LLMHOST LXC 111 — llama-swap models (RTX PRO 4000 24GB) ──────────────────

const LLMHOST_MODELS: SeedModel[] = [
  {
    id: "llmhost:glm-4.7-flash",
    name: "GLM 4.7 Flash (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/glm-4.7-flash/GLM-4.7-Flash-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(18) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 131072 --n-gpu-layers 999 " + FA,
    },
    capability: {
      param_count: null, tool_calling: "unverified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "17.52GB weights; MoE with full-MHA (heavy KV); managed by llama-swap",
  },
  {
    id: "llmhost:qwen3.6-35b-a3b",
    name: "Qwen 3.6 35B A3B (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(23) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 131072 --n-gpu-layers 999 " + FA,
    },
    capability: {
      param_count: "35B", tool_calling: "verified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "function-calling", "code"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "22.36GB; hybrid attention; tightest VRAM budget on this card",
  },
  {
    id: "llmhost:seed-oss-36b",
    name: "Seed OSS 36B (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/seed-oss-36b/Seed-OSS-36B-Instruct-IQ4_XS.gguf",
    quant: "IQ4_XS",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(20) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 32768 --n-gpu-layers 999 " + FA,
    },
    capability: {
      param_count: "36B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 32768,
      specialties: ["code", "reasoning"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "Dense 64-layer; ctx capped at 32K to avoid OOM",
  },
  {
    id: "llmhost:gpt-oss-20b",
    name: "GPT OSS 20B (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/gpt-oss-20b/gpt-oss-20b-UD-Q8_K_XL.gguf",
    quant: "UD-Q8_K_XL",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(14) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 262144 --n-gpu-layers 999 " + FA,
    },
    capability: {
      param_count: "20B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 262144,
      specialties: ["reasoning"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "MoE with MXFP4 experts; 262K ctx fits due to light KV",
  },
  {
    id: "llmhost:qwen3-coder-30b",
    name: "Qwen3 Coder 30B A3B (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/qwen3-coder-30b/Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(18) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 131072 --n-gpu-layers 999 " + FA,
    },
    capability: {
      param_count: "30B", tool_calling: "verified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["code", "function-calling"], has_vision: false, has_mmproj: false, mmproj_path: null,
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "MoE A3B coder",
  },
  {
    id: "llmhost:qwen3.8-27b",
    name: "Qwen 3.8 27B UD-Q4_K_XL (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(19) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 131072 --n-gpu-layers 999 " + FA +
        " --mmproj /models/qwen3.8-27b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "27B", tool_calling: "verified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["reasoning", "vision", "function-calling"], has_vision: true, has_mmproj: true,
      mmproj_path: "/models/qwen3.8-27b/mmproj-F16.gguf",
    },
    role_tags: ["orchestrator-eligible", "agent-eligible"],
    enabled: true, notes: "SSM/linear hybrid attention; vision-capable",
  },
  {
    id: "llmhost:gemma-4-12b",
    name: "Gemma 4 12B (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/gemma-4-12b/gemma-4-12b-it-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(7) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 262144 --n-gpu-layers 999 --jinja " + FA +
        " --mmproj /models/gemma-4-12b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "12B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 262144,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/models/gemma-4-12b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "QAT quant; translation + multimodal",
  },
  {
    id: "llmhost:qwen3vl-8b",
    name: "Qwen3 VL 8B (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/qwen3vl-8b/Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(7) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 8192 --n-gpu-layers 999 --jinja " + FA +
        " --mmproj /models/qwen3vl-8b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "8B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 8192,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/models/qwen3vl-8b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "ADA alt-text; image classification",
  },
  {
    id: "llmhost:qwen35-4b",
    name: "Qwen 3.5 4B (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/qwen35-4b/Qwen3.5-4B-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(4) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 32768 --n-gpu-layers 999 --jinja " + FA +
        " --mmproj /models/qwen35-4b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "4B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 32768,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/models/qwen35-4b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "201-language; thinking + non-thinking",
  },
  {
    id: "llmhost:qwen35-9b",
    name: "Qwen 3.5 9B (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/qwen35-9b/Qwen3.5-9B-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(7) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 32768 --n-gpu-layers 999 --jinja " + FA +
        " --mmproj /models/qwen35-9b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "9B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 32768,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/models/qwen35-9b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: null,
  },
  {
    id: "llmhost:gemma4-e4b",
    name: "Gemma 4 E4B (Llmhost)",
    backend: "llama-swap",
    weights_path: "/models/gemma4-e4b/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf",
    quant: "UD-Q4_K_XL",
    placement: {
      host_id: "llmhost-llm", gpus: [RTX_PRO], mode: "single",
      vram_req: { [RTX_PRO]: mib(6) },
      llama_tree: "llama-swap", llama_binary: "",
      launch_args: "--ctx-size 131072 --n-gpu-layers 999 --jinja " + FA +
        " --mmproj /models/gemma4-e4b/mmproj-F16.gguf",
    },
    capability: {
      param_count: "4B", tool_calling: "unverified",
      tokens_sec: null, ctx_len: 131072,
      specialties: ["vision"], has_vision: true, has_mmproj: true,
      mmproj_path: "/models/gemma4-e4b/mmproj-F16.gguf",
    },
    role_tags: ["agent-eligible"],
    enabled: true, notes: "Native audio input; QAT quant",
  },
];

// ── entry point ───────────────────────────────────────────────────────────────

export function seedModels() {
  const all: SeedModel[] = [
    ...GPUHOST_TINY,
    ...GPUHOST_SMALL_VISION,
    ...GPUHOST_SINGLE_A100,
    ...GPUHOST_DUAL_A100,
    ...GPUHOST_ALL_GPU,
    ...GPUHOST_ALL_GPU_CPU_MOE,
    ...GPUHOST_DUAL_A100_CPU_MOE,
    ...LLMHOST_MODELS,
  ];

  for (const m of all) {
    upsertModel(m);
  }

  return all.length;
}
