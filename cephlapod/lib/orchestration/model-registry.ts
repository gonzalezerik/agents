import { getDb } from "./db";
import type { Model, ModelPlacement, ModelCapability, ModelWarning } from "./types";

// ── helpers ──────────────────────────────────────────────────────────────────

function rowToModel(row: Record<string, unknown>): Model {
  return {
    id: row.id as string,
    name: row.name as string,
    backend: row.backend as Model["backend"],
    weights_path: row.weights_path as string,
    quant: (row.quant as string | null),
    placement: JSON.parse(row.placement_json as string) as ModelPlacement,
    capability: JSON.parse(row.capability_json as string) as ModelCapability,
    role_tags: JSON.parse(row.role_tags_json as string),
    enabled: (row.enabled as number) === 1,
    notes: (row.notes as string | null),
    created_at: row.created_at as string,
    updated_at: row.updated_at as string,
  };
}

// ── validation ───────────────────────────────────────────────────────────────

export function validateModel(model: Omit<Model, "created_at" | "updated_at">): ModelWarning[] {
  const warnings: ModelWarning[] = [];
  const isOrchEligible = model.role_tags.includes("orchestrator-eligible");

  if (isOrchEligible) {
    if (model.capability.tool_calling !== "verified") {
      warnings.push({
        code: "no-tool-calling",
        message: `Orchestrator-eligible but tool_calling is "${model.capability.tool_calling}". This model may fail to route tasks.`,
        severity: "warn",
      });
    }
    if (model.capability.ctx_len !== null && model.capability.ctx_len < 8192) {
      warnings.push({
        code: "ctx-too-small",
        message: `Context window ${model.capability.ctx_len} is too small to hold a routing prompt + task. Minimum recommended: 8192.`,
        severity: "warn",
      });
    }
  }

  const { gpus, vram_req, mode } = model.placement;
  if (mode === "tensor-parallel" && gpus.length > 1) {
    // Heterogeneous TP is not viable — flag if mixing A100 + 3090
    const a100_uuid = "GPU-a1000001";
    const rtx_uuid = "GPU-30900001";
    const hasA100 = gpus.some((g) => g.startsWith(a100_uuid) || g.startsWith("GPU-a1000002"));
    const has3090 = gpus.some((g) => g.startsWith(rtx_uuid));
    if (hasA100 && has3090) {
      warnings.push({
        code: "placement-conflict",
        message: "Tensor-parallel across A100 + RTX 3090 is not viable (heterogeneous heads). Use pipeline or layer-split instead.",
        severity: "block",
      });
    }
  }

  if (model.placement.llama_tree !== "llama-swap") {
    const totalVram = Object.values(vram_req).reduce((s, v) => s + v, 0);
    // Rough check only; mc-agent does the real check at launch time
    if (totalVram === 0 && gpus.length > 0) {
      warnings.push({
        code: "vram-exceeds-gpu",
        message: "No VRAM requirement specified but GPU placement defined.",
        severity: "warn",
      });
    }
  }

  return warnings;
}

// ── CRUD ─────────────────────────────────────────────────────────────────────

export function listModels(opts?: { enabled_only?: boolean }): Model[] {
  const db = getDb();
  const query = opts?.enabled_only
    ? "SELECT * FROM models WHERE enabled = 1 ORDER BY name"
    : "SELECT * FROM models ORDER BY name";
  return (db.prepare(query).all() as Record<string, unknown>[]).map(rowToModel);
}

export function getModel(id: string): Model | null {
  const db = getDb();
  const row = db.prepare("SELECT * FROM models WHERE id = ?").get(id) as Record<string, unknown> | undefined;
  return row ? rowToModel(row) : null;
}

export function upsertModel(model: Omit<Model, "created_at" | "updated_at">): Model {
  const db = getDb();
  const now = new Date().toISOString();
  const existing = getModel(model.id);
  const created_at = existing?.created_at ?? now;

  db.prepare(`
    INSERT INTO models (id, name, backend, weights_path, quant, placement_json, capability_json, role_tags_json, enabled, notes, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
      name = excluded.name,
      backend = excluded.backend,
      weights_path = excluded.weights_path,
      quant = excluded.quant,
      placement_json = excluded.placement_json,
      capability_json = excluded.capability_json,
      role_tags_json = excluded.role_tags_json,
      enabled = excluded.enabled,
      notes = excluded.notes,
      updated_at = excluded.updated_at
  `).run(
    model.id, model.name, model.backend, model.weights_path, model.quant ?? null,
    JSON.stringify(model.placement), JSON.stringify(model.capability),
    JSON.stringify(model.role_tags), model.enabled ? 1 : 0,
    model.notes ?? null, created_at, now
  );

  return getModel(model.id)!;
}

export function deleteModel(id: string): boolean {
  const db = getDb();
  // Remove from pool and clear orchestrator slot first
  db.prepare("DELETE FROM agent_pool WHERE model_id = ?").run(id);
  db.prepare("UPDATE orchestrator_slot SET model_id = NULL WHERE model_id = ?").run(id);
  const info = db.prepare("DELETE FROM models WHERE id = ?").run(id);
  return info.changes > 0;
}

export function setModelEnabled(id: string, enabled: boolean): void {
  const db = getDb();
  db.prepare("UPDATE models SET enabled = ?, updated_at = ? WHERE id = ?")
    .run(enabled ? 1 : 0, new Date().toISOString(), id);
}
