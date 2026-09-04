import Database from "better-sqlite3";
import path from "path";
import fs from "fs";

const DB_DIR = process.env.MC_STATE_DIR ?? "/var/lib/mission-control";
const DB_PATH = path.join(DB_DIR, "state.db");

let _db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (_db) return _db;
  fs.mkdirSync(DB_DIR, { recursive: true });
  _db = new Database(DB_PATH);
  _db.pragma("journal_mode = WAL");
  _db.pragma("foreign_keys = ON");
  migrate(_db);
  return _db;
}

function migrate(db: Database.Database) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
  `);
  const row = db.prepare("SELECT version FROM schema_version").get() as { version: number } | undefined;
  const current = row?.version ?? 0;
  if (current < 1) applyV1(db);
}

function applyV1(db: Database.Database) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS models (
      id              TEXT PRIMARY KEY,
      name            TEXT NOT NULL,
      backend         TEXT NOT NULL,
      weights_path    TEXT NOT NULL,
      quant           TEXT,
      placement_json  TEXT NOT NULL,
      capability_json TEXT NOT NULL,
      role_tags_json  TEXT NOT NULL DEFAULT '[]',
      enabled         INTEGER NOT NULL DEFAULT 1,
      notes           TEXT,
      created_at      TEXT NOT NULL,
      updated_at      TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS orchestrator_slot (
      id        INTEGER PRIMARY KEY DEFAULT 1,
      model_id  TEXT REFERENCES models(id),
      set_at    TEXT NOT NULL,
      set_by    TEXT NOT NULL DEFAULT 'dashboard'
    );
    -- Seed with empty slot
    INSERT OR IGNORE INTO orchestrator_slot (id, model_id, set_at, set_by)
    VALUES (1, NULL, datetime('now'), 'system');

    CREATE TABLE IF NOT EXISTS agent_pool (
      model_id    TEXT PRIMARY KEY REFERENCES models(id),
      added_at    TEXT NOT NULL,
      auto_resume INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS routing_log (
      id                      INTEGER PRIMARY KEY AUTOINCREMENT,
      ts                      TEXT NOT NULL,
      session_id              TEXT NOT NULL,
      prompt_summary          TEXT,
      orchestrator_model_id   TEXT,
      agent_model_id          TEXT,
      routing_reason          TEXT,
      latency_plan_ms         INTEGER,
      latency_agent_ms        INTEGER,
      tokens_in               INTEGER,
      tokens_out              INTEGER,
      outcome                 TEXT NOT NULL DEFAULT 'success',
      error_detail            TEXT,
      full_transcript         TEXT
    );
    CREATE INDEX IF NOT EXISTS routing_log_ts ON routing_log(ts DESC);
    CREATE INDEX IF NOT EXISTS routing_log_session ON routing_log(session_id);

    CREATE TABLE IF NOT EXISTS reconciler_state (
      id                             INTEGER PRIMARY KEY DEFAULT 1,
      frozen                         INTEGER NOT NULL DEFAULT 0,
      last_run                       TEXT,
      last_error                     TEXT,
      transition_count_last_minute   INTEGER NOT NULL DEFAULT 0,
      last_transition_window_start   TEXT
    );
    INSERT OR IGNORE INTO reconciler_state (id) VALUES (1);

    CREATE TABLE IF NOT EXISTS shim_sessions (
      id             TEXT PRIMARY KEY,
      connected_at   TEXT NOT NULL,
      last_seen      TEXT NOT NULL,
      client_ip      TEXT NOT NULL,
      passthrough    INTEGER NOT NULL DEFAULT 0,
      request_count  INTEGER NOT NULL DEFAULT 0
    );

    INSERT OR REPLACE INTO schema_version (version) VALUES (1);
  `);
}
