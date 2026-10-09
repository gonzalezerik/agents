"""
Append-only event log for full session audit trails.
Every prompt, orchestrator decision, tool call, agent response, error, repair
gets one row. Stored in SQLite with WAL mode so shim and mc-agent can read
concurrently.

Event types:
  user_message        — incoming Anthropic request (full messages array)
  orchestrator_plan   — routing prompt + raw orchestrator response + latency
  agent_selected      — model_id chosen + reason string
  tool_call           — tool_use block intercepted from agent
  tool_result         — tool_result block sent back
  agent_response      — completed agent turn (full content + usage)
  final_response      — what was streamed back to the client
  error               — exception in any phase
  repair              — malformed tool JSON detected and repaired
  passthrough_forward — passthrough mode: direct forward with no orchestration
"""
import sqlite3, json, time, threading
from config import EVENTS_DB

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(EVENTS_DB, check_same_thread=False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
          id                TEXT PRIMARY KEY,
          started_at        TEXT NOT NULL,
          last_seen         TEXT NOT NULL,
          client_ip         TEXT NOT NULL DEFAULT '',
          passthrough       INTEGER NOT NULL DEFAULT 0,
          request_count     INTEGER NOT NULL DEFAULT 0,
          orchestrator_model_id TEXT,
          title             TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_events (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id  TEXT NOT NULL,
          seq         INTEGER NOT NULL,
          ts          TEXT NOT NULL,
          event_type  TEXT NOT NULL,
          payload     TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS session_events_idx ON session_events(session_id, seq)"
    )
    conn.commit()
    return conn


_db: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _db
    if _db is None:
        import os
        os.makedirs(EVENTS_DB.rsplit("/", 1)[0], exist_ok=True)
        _db = _conn()
    return _db


# ── Session ───────────────────────────────────────────────────────────────────

def ensure_session(session_id: str, client_ip: str = "", passthrough: bool = False) -> None:
    now = _ts()
    with _lock:
        db().execute("""
            INSERT OR IGNORE INTO sessions (id, started_at, last_seen, client_ip, passthrough)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, now, now, client_ip, int(passthrough)))
        db().execute("UPDATE sessions SET last_seen = ? WHERE id = ?", (now, session_id))
        db().commit()


def set_session_title(session_id: str, title: str) -> None:
    with _lock:
        db().execute(
            "UPDATE sessions SET title = ? WHERE id = ? AND title IS NULL",
            (title[:120], session_id)
        )
        db().commit()


def set_orchestrator(session_id: str, model_id: str) -> None:
    with _lock:
        db().execute(
            "UPDATE sessions SET orchestrator_model_id = ? WHERE id = ?",
            (model_id, session_id)
        )
        db().commit()


def increment_request_count(session_id: str) -> None:
    with _lock:
        db().execute(
            "UPDATE sessions SET request_count = request_count + 1, last_seen = ? WHERE id = ?",
            (_ts(), session_id)
        )
        db().commit()


def list_sessions(limit: int = 100) -> list[dict]:
    rows = db().execute(
        "SELECT * FROM sessions ORDER BY last_seen DESC LIMIT ?", (limit,)
    ).fetchall()
    cols = [d[0] for d in db().execute("SELECT * FROM sessions LIMIT 0").description]
    return [dict(zip(cols, r)) for r in rows]


# ── Events ────────────────────────────────────────────────────────────────────

def _next_seq(session_id: str) -> int:
    row = db().execute(
        "SELECT MAX(seq) FROM session_events WHERE session_id = ?", (session_id,)
    ).fetchone()
    return (row[0] or 0) + 1


def _ts() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


def log(session_id: str, event_type: str, payload: dict) -> int:
    with _lock:
        seq = _next_seq(session_id)
        cur = db().execute("""
            INSERT INTO session_events (session_id, seq, ts, event_type, payload)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, seq, _ts(), event_type, json.dumps(payload)))
        db().commit()
        return cur.lastrowid


def get_events(session_id: str) -> list[dict]:
    rows = db().execute(
        "SELECT id, session_id, seq, ts, event_type, payload "
        "FROM session_events WHERE session_id = ? ORDER BY seq",
        (session_id,)
    ).fetchall()
    return [
        {
            "id": r[0], "session_id": r[1], "seq": r[2],
            "ts": r[3], "event_type": r[4],
            "payload": json.loads(r[5]),
        }
        for r in rows
    ]
