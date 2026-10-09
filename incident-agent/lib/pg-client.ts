/**
 * Postgres access for the incident agent: the `agent_runs` audit log.
 * Extracted from the ops dashboard's larger pg-client, keeping only what
 * this agent uses.
 */
import { Pool } from "pg";

let pool: Pool | null = null;

function getPool(): Pool | null {
  if (!process.env.DATABASE_URL) return null;
  if (!pool) {
    pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 5 });
  }
  return pool;
}

let schemaReady = false;

async function ensureSchema(): Promise<boolean> {
  const p = getPool();
  if (!p) return false;
  if (schemaReady) return true;
  await p.query(`
    CREATE TABLE IF NOT EXISTS agent_runs (
      id TEXT PRIMARY KEY,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      entity TEXT NOT NULL,
      summary TEXT NOT NULL,
      mode TEXT NOT NULL DEFAULT 'report-only',
      tool_access TEXT NOT NULL DEFAULT 'read-only',
      outcome TEXT NOT NULL,
      tool_name TEXT,
      confidence REAL,
      investigation TEXT,
      proposed_action JSONB,
      applied_at TIMESTAMPTZ,
      applied_result TEXT
    )
  `);
  schemaReady = true;
  return true;
}

export interface AgentRun {
  id: string;
  created_at: string;
  entity: string;
  summary: string;
  mode: string;
  tool_access: string;
  outcome: string;
  tool_name: string | null;
  confidence: number | null;
  investigation: string | null;
  proposed_action: Record<string, unknown> | null;
  applied_at: string | null;
  applied_result: string | null;
}

export async function insertAgentRun(run: Omit<AgentRun, "id" | "created_at" | "applied_at" | "applied_result">): Promise<AgentRun | null> {
  const p = getPool();
  if (!p || !(await ensureSchema())) return null;
  const id = crypto.randomUUID();
  const res = await p.query(
    `INSERT INTO agent_runs (id, entity, summary, mode, tool_access, outcome, tool_name, confidence, investigation, proposed_action)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *`,
    [id, run.entity, run.summary, run.mode, run.tool_access, run.outcome, run.tool_name, run.confidence, run.investigation, run.proposed_action]
  );
  return res.rows[0];
}

export async function listAgentRuns(limit = 50): Promise<AgentRun[]> {
  const p = getPool();
  if (!p || !(await ensureSchema())) return [];
  const res = await p.query(`SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT $1`, [limit]);
  return res.rows;
}

export async function getAgentRun(id: string): Promise<AgentRun | null> {
  const p = getPool();
  if (!p || !(await ensureSchema())) return null;
  const res = await p.query(`SELECT * FROM agent_runs WHERE id = $1`, [id]);
  return res.rows[0] ?? null;
}

export async function markRunApplied(id: string, result: string, outcome = "executed"): Promise<void> {
  const p = getPool();
  if (!p || !(await ensureSchema())) return;
  await p.query(`UPDATE agent_runs SET applied_at = now(), applied_result = $2, outcome = $3 WHERE id = $1`, [id, result, outcome]);
}

