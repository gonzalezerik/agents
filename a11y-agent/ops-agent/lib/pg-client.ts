/**
 * Postgres access for the a11y agent: the shared `agent_runs` audit log and
 * the `a11y_reports` table. Extracted from the ops dashboard's larger
 * pg-client, keeping only what the accessibility flow uses.
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

// ---------- A11y reports ----------

let a11ySchemaReady = false;

async function ensureA11ySchema(): Promise<boolean> {
  const p = getPool();
  if (!p) return false;
  if (a11ySchemaReady) return true;
  await p.query(`
    DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'a11y_report_status') THEN
        CREATE TYPE a11y_report_status AS ENUM ('pending','investigating','fix_proposed','fix_deployed','dismissed');
      END IF;
    END $$;
    CREATE TABLE IF NOT EXISTS a11y_reports (
      id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      url TEXT NOT NULL,
      description TEXT NOT NULL,
      user_agent TEXT,
      ip TEXT,
      reporter_email TEXT,
      status a11y_report_status NOT NULL DEFAULT 'pending',
      agent_run_id TEXT REFERENCES agent_runs(id)
    );
    ALTER TABLE a11y_reports ADD COLUMN IF NOT EXISTS reporter_email TEXT;
  `);
  a11ySchemaReady = true;
  return true;
}

export interface A11yReport {
  id: string;
  created_at: string;
  updated_at: string;
  url: string;
  description: string;
  user_agent: string | null;
  ip: string | null;
  reporter_email: string | null;
  status: "pending" | "investigating" | "fix_proposed" | "fix_deployed" | "dismissed";
  agent_run_id: string | null;
}

export async function insertA11yReport(report: Omit<A11yReport, "id" | "created_at" | "updated_at" | "agent_run_id" | "status">): Promise<A11yReport | null> {
  const p = getPool();
  if (!p || !(await ensureSchema()) || !(await ensureA11ySchema())) return null;
  const res = await p.query(
    `INSERT INTO a11y_reports (url, description, user_agent, ip, reporter_email) VALUES ($1,$2,$3,$4,$5) RETURNING *`,
    [report.url, report.description, report.user_agent, report.ip, report.reporter_email ?? null]
  );
  return res.rows[0] ?? null;
}

export async function getA11yReport(id: string): Promise<A11yReport | null> {
  const p = getPool();
  if (!p || !(await ensureA11ySchema())) return null;
  const res = await p.query(`SELECT * FROM a11y_reports WHERE id = $1`, [id]);
  return res.rows[0] ?? null;
}

export async function listA11yReports(limit = 50): Promise<A11yReport[]> {
  const p = getPool();
  if (!p || !(await ensureA11ySchema())) return [];
  const res = await p.query(`SELECT * FROM a11y_reports ORDER BY created_at DESC LIMIT $1`, [limit]);
  return res.rows;
}

export async function updateA11yReportStatus(id: string, status: A11yReport["status"]): Promise<void> {
  const p = getPool();
  if (!p || !(await ensureA11ySchema())) return;
  await p.query(`UPDATE a11y_reports SET status = $2, updated_at = now() WHERE id = $1`, [id, status]);
}

export async function linkA11yReportToRun(reportId: string, runId: string): Promise<void> {
  const p = getPool();
  if (!p || !(await ensureA11ySchema())) return;
  await p.query(`UPDATE a11y_reports SET agent_run_id = $2, updated_at = now() WHERE id = $1`, [reportId, runId]);
}


