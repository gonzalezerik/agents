"""
Model registry reader — reads from the shared SQLite that mission-control writes.
mc-agent does NOT own the schema; it reads what the dashboard seeded.
"""
import sqlite3, json
from typing import Any
from config import DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_model(model_id: str) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["placement"] = json.loads(d["placement_json"])
    d["capability"] = json.loads(d["capability_json"])
    d["role_tags"]  = json.loads(d["role_tags_json"])
    return d
