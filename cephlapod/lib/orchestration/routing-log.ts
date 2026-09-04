import { getDb } from "./db";
import type { RoutingLogEntry, RoutingOutcome } from "./types";

export interface InsertRoutingLogArgs {
  session_id: string;
  prompt_summary?: string;
  orchestrator_model_id?: string;
  agent_model_id?: string;
  routing_reason?: string;
  latency_plan_ms?: number;
  latency_agent_ms?: number;
  tokens_in?: number;
  tokens_out?: number;
  outcome: RoutingOutcome;
  error_detail?: string;
  full_transcript?: string;
}

export function insertRoutingLog(args: InsertRoutingLogArgs): number {
  const db = getDb();
  const info = db.prepare(`
    INSERT INTO routing_log
      (ts, session_id, prompt_summary, orchestrator_model_id, agent_model_id,
       routing_reason, latency_plan_ms, latency_agent_ms, tokens_in, tokens_out,
       outcome, error_detail, full_transcript)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    new Date().toISOString(),
    args.session_id,
    args.prompt_summary ?? null,
    args.orchestrator_model_id ?? null,
    args.agent_model_id ?? null,
    args.routing_reason ?? null,
    args.latency_plan_ms ?? null,
    args.latency_agent_ms ?? null,
    args.tokens_in ?? null,
    args.tokens_out ?? null,
    args.outcome,
    args.error_detail ?? null,
    args.full_transcript ?? null,
  );
  return info.lastInsertRowid as number;
}

export function listRoutingLog(opts?: { limit?: number; session_id?: string }): RoutingLogEntry[] {
  const db = getDb();
  const limit = opts?.limit ?? 100;
  const rows = opts?.session_id
    ? db.prepare("SELECT id,ts,session_id,prompt_summary,orchestrator_model_id,agent_model_id,routing_reason,latency_plan_ms,latency_agent_ms,tokens_in,tokens_out,outcome,error_detail FROM routing_log WHERE session_id = ? ORDER BY ts DESC LIMIT ?").all(opts.session_id, limit)
    : db.prepare("SELECT id,ts,session_id,prompt_summary,orchestrator_model_id,agent_model_id,routing_reason,latency_plan_ms,latency_agent_ms,tokens_in,tokens_out,outcome,error_detail FROM routing_log ORDER BY ts DESC LIMIT ?").all(limit);
  return rows as RoutingLogEntry[];
}

export function getRoutingLogTranscript(id: number): string | null {
  const db = getDb();
  const row = db.prepare("SELECT full_transcript FROM routing_log WHERE id = ?").get(id) as
    { full_transcript: string | null } | undefined;
  return row?.full_transcript ?? null;
}

// Prune entries older than `days` to keep DB from growing unbounded
export function pruneRoutingLog(days = 30): number {
  const db = getDb();
  const cutoff = new Date(Date.now() - days * 86400 * 1000).toISOString();
  return db.prepare("DELETE FROM routing_log WHERE ts < ?").run(cutoff).changes;
}
