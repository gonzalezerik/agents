import { getDb } from "./db";
import type { OrchestratorSlot, AgentPoolEntry } from "./types";

// ── Orchestrator slot ─────────────────────────────────────────────────────────

export function getOrchestratorSlot(): OrchestratorSlot {
  const db = getDb();
  const row = db.prepare("SELECT model_id, set_at, set_by FROM orchestrator_slot WHERE id = 1").get() as
    { model_id: string | null; set_at: string; set_by: string };
  return { model_id: row.model_id, set_at: row.set_at, set_by: row.set_by };
}

export function setOrchestrator(model_id: string | null, set_by = "dashboard"): OrchestratorSlot {
  const db = getDb();
  const now = new Date().toISOString();
  db.prepare("UPDATE orchestrator_slot SET model_id = ?, set_at = ?, set_by = ? WHERE id = 1")
    .run(model_id, now, set_by);
  return { model_id, set_at: now, set_by };
}

// ── Agent pool ────────────────────────────────────────────────────────────────

export function listAgentPool(): AgentPoolEntry[] {
  const db = getDb();
  return (db.prepare("SELECT model_id, added_at, auto_resume FROM agent_pool ORDER BY added_at").all() as
    { model_id: string; added_at: string; auto_resume: number }[]).map((r) => ({
    model_id: r.model_id,
    added_at: r.added_at,
    auto_resume: r.auto_resume === 1,
  }));
}

export function addToAgentPool(model_id: string, auto_resume = false): AgentPoolEntry {
  const db = getDb();
  const now = new Date().toISOString();
  db.prepare("INSERT OR IGNORE INTO agent_pool (model_id, added_at, auto_resume) VALUES (?, ?, ?)")
    .run(model_id, now, auto_resume ? 1 : 0);
  return { model_id, added_at: now, auto_resume };
}

export function removeFromAgentPool(model_id: string): boolean {
  const db = getDb();
  return db.prepare("DELETE FROM agent_pool WHERE model_id = ?").run(model_id).changes > 0;
}

export function setAutoResume(model_id: string, auto_resume: boolean): void {
  const db = getDb();
  db.prepare("UPDATE agent_pool SET auto_resume = ? WHERE model_id = ?").run(auto_resume ? 1 : 0, model_id);
}
