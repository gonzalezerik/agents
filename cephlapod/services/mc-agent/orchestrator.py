"""
Orchestrator pool management for mc-agent.
Exposes /orchestrator/* endpoints that Mission Control calls to:
  - Read the agent pool (hosts + models + running state)
  - Accept heartbeats from lab-orch on the laptop
  - Patch model settings (enabled, is_orchestrator, capabilities)
  - Start/stop models (proxies to launcher)
  - Stream routing events for the live trace
"""
from __future__ import annotations
import datetime, json, os, sqlite3, time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from typing import Annotated

from config import TOKEN, HOST_ID

router = APIRouter(prefix="/orchestrator")

STATE_DB = os.environ.get("MC_STATE_DB", "/var/lib/mission-control/state.db")
EVENTS_DB = os.environ.get("MC_EVENTS_DB", "/var/lib/mc-agent/events.db")
SHIM_URL  = os.environ.get("MC_SHIM_URL",  "http://127.0.0.1:4000")
STALE_S   = 90


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_auth(authorization: Annotated[str | None, Header()] = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    if authorization.removeprefix("Bearer ") != TOKEN:
        raise HTTPException(403, "Invalid token")

Auth = Depends(require_auth)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _state_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(STATE_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _events_conn() -> sqlite3.Connection | None:
    if not os.path.exists(EVENTS_DB):
        return None
    conn = sqlite3.connect(EVENTS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_online(last_seen: str | None) -> bool:
    if not last_seen:
        return False
    try:
        ts = datetime.datetime.strptime(last_seen, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc
        )
        age = (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()
        return age < STALE_S
    except Exception:
        return False


def _ensure_hosts():
    """Create the hosts table if absent, and ensure gpuhost is always present."""
    with _state_conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS hosts (
                id               TEXT PRIMARY KEY,
                name             TEXT NOT NULL,
                ip               TEXT NOT NULL DEFAULT '',
                type             TEXT NOT NULL DEFAULT 'heartbeat',
                mc_agent_url     TEXT,
                heartbeat_token  TEXT NOT NULL DEFAULT '',
                last_seen        TEXT,
                created_at       TEXT NOT NULL DEFAULT ''
            )
        """)
        db.execute("""
            INSERT OR IGNORE INTO hosts (id, name, ip, type, mc_agent_url, heartbeat_token, last_seen, created_at)
            VALUES ('gpuhost', 'gpuhost', 'localhost', 'managed',
                    'http://localhost:4001', '', ?, ?)
        """, (_now(), _now()))
        db.commit()


def _accel_label(placement: dict, capability: dict) -> str:
    specs = capability.get("specialties", [])
    if "npu" in specs:
        return "NPU"
    gpus = placement.get("gpus", [])
    accel = placement.get("accelerator", "")
    if accel:
        return accel
    if not gpus:
        return "CPU"
    # Map first GPU UUID to a name if we can from gpu.py output
    return "GPU"


# ── GET /orchestrator/pool ────────────────────────────────────────────────────

@router.get("/pool", dependencies=[Auth])
def get_pool() -> dict:
    _ensure_hosts()

    import launcher
    running_ports: dict[str, int] = launcher.running_ports()

    db = _state_conn()

    # Hosts
    host_rows = db.execute("SELECT * FROM hosts ORDER BY type DESC, id").fetchall()
    # Models
    model_rows = db.execute(
        "SELECT * FROM models ORDER BY placement_json, id"
    ).fetchall()
    # Pool membership set
    pool_ids = {r["model_id"] for r in db.execute("SELECT model_id FROM agent_pool").fetchall()}
    # Orchestrator slot
    orch_row = db.execute("SELECT model_id FROM orchestrator_slot WHERE id=1").fetchone()
    orch_id  = orch_row["model_id"] if orch_row else None

    # Build host list
    hosts: list[dict] = []
    for h in host_rows:
        online = True if h["id"] == HOST_ID else _is_online(h["last_seen"])
        hosts.append({
            "id":           h["id"],
            "name":         h["name"],
            "ip":           h["ip"],
            "type":         h["type"],
            "mc_agent_url": h["mc_agent_url"],
            "last_seen":    h["last_seen"],
            "online":       online,
        })

    # Build model list
    models: list[dict] = []
    for m in model_rows:
        placement   = json.loads(m["placement_json"])
        capability  = json.loads(m["capability_json"])
        host_id_m   = placement.get("host_id", "")
        bridge_url  = placement.get("bridge_url")
        accel       = _accel_label(placement, capability)

        port: int | None = None
        if bridge_url:
            try:
                from urllib.parse import urlparse
                port = urlparse(bridge_url).port
            except Exception:
                pass
        elif host_id_m == HOST_ID and m["id"] in running_ports:
            port = running_ports[m["id"]]

        is_running = (m["id"] in running_ports) if host_id_m == HOST_ID else None
        in_pool    = m["id"] in pool_ids

        models.append({
            "id":           m["id"],
            "name":         m["name"],
            "host_id":      host_id_m,
            "backend":      m["backend"],
            "accelerator":  accel,
            "bridge_url":   bridge_url,
            "port":         port,
            "capabilities": capability.get("specialties", []),
            "tool_calling": capability.get("tool_calling", "unverified"),
            "param_count":  capability.get("param_count"),
            "ctx_len":      capability.get("ctx_len"),
            "enabled":      bool(m["enabled"]),
            "in_pool":      in_pool,
            "is_orchestrator": m["id"] == orch_id,
            "running":      is_running,
            "notes":        m["notes"],
        })

    agents_in_pool    = sum(1 for m in models if m["in_pool"] and m["enabled"])
    hosts_online      = sum(1 for h in hosts if h["online"])
    orch_running      = any(m["is_orchestrator"] and m["running"] for m in models)

    shim_up = False
    try:
        r = httpx.get(f"{SHIM_URL}/health", timeout=2)
        shim_up = r.status_code == 200
    except Exception:
        pass

    return {
        "hosts":                 hosts,
        "models":                models,
        "orchestrator_model_id": orch_id,
        "shim_up":               shim_up,
        "agents_in_pool":        agents_in_pool,
        "hosts_online":          hosts_online,
        "orchestrator_running":  orch_running,
    }


# ── POST /orchestrator/heartbeat ──────────────────────────────────────────────

class HBModel(BaseModel):
    id:           str
    name:         str | None = None
    bridge_url:   str
    accelerator:  str = "iGPU"
    capabilities: list[str] = []

class HeartbeatReq(BaseModel):
    host_id:   str
    host_name: str | None = None
    host_ip:   str | None = None
    models:    list[HBModel] = []


@router.post("/heartbeat", dependencies=[Auth])
def heartbeat(req: HeartbeatReq) -> dict:
    _ensure_hosts()
    now = _now()

    # Leaving: empty models list
    leaving = len(req.models) == 0

    with _state_conn() as db:
        if leaving:
            # Push last_seen back past the stale window
            stale_ts = (
                datetime.datetime.utcnow() - datetime.timedelta(seconds=STALE_S + 60)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            db.execute("UPDATE hosts SET last_seen=? WHERE id=?", (stale_ts, req.host_id))
        else:
            db.execute("""
                INSERT INTO hosts (id, name, ip, type, heartbeat_token, last_seen, created_at)
                VALUES (?, ?, ?, 'heartbeat', '', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    name = COALESCE(excluded.name, name),
                    ip   = COALESCE(excluded.ip, ip)
            """, (req.host_id, req.host_name or req.host_id, req.host_ip or "", now, now))

            for m in req.models:
                mid = f"{req.host_id}:{m.id}"
                placement_j = json.dumps({
                    "host_id":    req.host_id,
                    "bridge_url": m.bridge_url,
                    "accelerator": m.accelerator,
                    "gpus": [],
                    "llama_binary": "",
                    "launch_args": "",
                })
                capability_j = json.dumps({
                    "specialties": m.capabilities,
                    "tool_calling": "unverified",
                })
                db.execute("""
                    INSERT INTO models
                        (id, name, backend, weights_path, placement_json, capability_json,
                         role_tags_json, enabled, created_at, updated_at)
                    VALUES (?, ?, 'heartbeat', '', ?, ?, '[]', 1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name           = excluded.name,
                        placement_json = excluded.placement_json,
                        capability_json= excluded.capability_json,
                        updated_at     = excluded.updated_at
                """, (mid, m.name or m.id, placement_j, capability_j, now, now))

        db.commit()

    return {"ok": True, "action": "leave" if leaving else "heartbeat"}


# ── PATCH /orchestrator/models/{model_id} ─────────────────────────────────────

class ModelPatch(BaseModel):
    enabled:         bool | None = None
    is_orchestrator: bool | None = None
    capability_json: dict | None = None


@router.patch("/models/{model_id:path}", dependencies=[Auth])
def patch_model(model_id: str, patch: ModelPatch) -> dict:
    with _state_conn() as db:
        row = db.execute("SELECT id FROM models WHERE id=?", (model_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Model {model_id!r} not found")

        if patch.enabled is not None:
            db.execute("UPDATE models SET enabled=?, updated_at=? WHERE id=?",
                       (int(patch.enabled), _now(), model_id))
            if patch.enabled:
                db.execute("""
                    INSERT OR IGNORE INTO agent_pool (model_id, added_at, auto_resume)
                    VALUES (?, ?, 0)
                """, (model_id, _now()))
            else:
                db.execute("DELETE FROM agent_pool WHERE model_id=?", (model_id,))

        if patch.is_orchestrator is not None:
            if patch.is_orchestrator:
                db.execute("""
                    INSERT INTO orchestrator_slot (id, model_id, set_at, set_by)
                    VALUES (1, ?, ?, 'dashboard')
                    ON CONFLICT(id) DO UPDATE SET model_id=excluded.model_id, set_at=excluded.set_at
                """, (model_id, _now()))
            else:
                # Only clear if this model was the orchestrator
                db.execute(
                    "UPDATE orchestrator_slot SET model_id=NULL WHERE id=1 AND model_id=?",
                    (model_id,)
                )

        if patch.capability_json is not None:
            db.execute("UPDATE models SET capability_json=?, updated_at=? WHERE id=?",
                       (json.dumps(patch.capability_json), _now(), model_id))

        db.commit()

    return {"ok": True}


# ── POST /orchestrator/models/{model_id}/start|stop ──────────────────────────

@router.post("/models/{model_id:path}/start", dependencies=[Auth])
def start_model(model_id: str) -> dict:
    import launcher
    db  = _state_conn()
    row = db.execute("SELECT placement_json FROM models WHERE id=?", (model_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Model {model_id!r} not found")
    placement = json.loads(row["placement_json"])
    if placement.get("host_id") != HOST_ID:
        raise HTTPException(400, "Cannot start models on remote hosts from this agent")
    try:
        pid = launcher.start(model_id)
        return {"pid": pid}
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))


@router.post("/models/{model_id:path}/stop", dependencies=[Auth])
def stop_model(model_id: str) -> dict:
    import launcher
    db  = _state_conn()
    row = db.execute("SELECT placement_json FROM models WHERE id=?", (model_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Model {model_id!r} not found")
    placement = json.loads(row["placement_json"])
    if placement.get("host_id") != HOST_ID:
        raise HTTPException(400, "Cannot stop models on remote hosts from this agent")
    found = launcher.stop(model_id, reason="dashboard-stop")
    if not found:
        raise HTTPException(404, f"Model {model_id!r} is not running")
    return {"ok": True}


# ── GET /orchestrator/events?since={cursor} ───────────────────────────────────
# Polling endpoint — returns new events since the given rowid cursor.
# Mission Control polls this at 2s and fans results out over its SSE channel.

@router.get("/events", dependencies=[Auth])
def get_events(since: int = 0, limit: int = 50) -> list[dict]:
    conn = _events_conn()
    if not conn:
        return []
    rows = conn.execute(
        "SELECT e.id, e.session_id, e.seq, e.ts, e.event_type, e.payload,"
        " COALESCE(s.client_ip, '') AS client_ip"
        " FROM session_events e"
        " LEFT JOIN sessions s ON e.session_id = s.id"
        " WHERE e.id > ? ORDER BY e.id LIMIT ?",
        (since, limit),
    ).fetchall()
    return [
        {
            "id":         r["id"],
            "session_id": r["session_id"],
            "seq":        r["seq"],
            "ts":         r["ts"],
            "event_type": r["event_type"],
            "payload":    json.loads(r["payload"]),
            "client_ip":  r["client_ip"],
        }
        for r in rows
    ]


# ── GET /orchestrator/stats ──────────────────────────────────────────────────
# Aggregate routing events for charts: routes-by-agent and latency-by-agent.

import statistics as _stats_mod

@router.get("/stats", dependencies=[Auth])

# ── GET /orchestrator/stats ──────────────────────────────────────────────────

@router.get("/stats", dependencies=[Auth])
def get_stats(window_hours: int = 24) -> dict:
    conn = _events_conn()
    if not conn:
        return {"route_buckets": [], "latency_buckets": [], "agents": []}

    since_dt = datetime.datetime.utcnow() - datetime.timedelta(hours=window_hours)
    since    = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    route_rows = conn.execute(
        "SELECT strftime('%Y-%m-%dT%H:00:00Z', ts) AS hour,"
        " json_extract(payload, '$.model_id') AS model_id,"
        " COUNT(*) AS cnt"
        " FROM session_events"
        " WHERE event_type = 'agent_selected'"
        "   AND ts >= ?"
        "   AND json_extract(payload, '$.model_id') IS NOT NULL"
        " GROUP BY hour, model_id ORDER BY hour",
        (since,)
    ).fetchall()

    lat_rows = conn.execute(
        "SELECT strftime('%Y-%m-%dT%H:00:00Z', ts) AS hour,"
        " json_extract(payload, '$.model_id') AS model_id,"
        " CAST(json_extract(payload, '$.latency_ms') AS INTEGER) AS latency_ms"
        " FROM session_events"
        " WHERE event_type = 'agent_response'"
        "   AND ts >= ?"
        "   AND json_extract(payload, '$.latency_ms') IS NOT NULL"
        " ORDER BY hour, model_id",
        (since,)
    ).fetchall()

    from collections import defaultdict
    lat_map = defaultdict(list)
    for r in lat_rows:
        lat_map[(r["hour"], r["model_id"])].append(r["latency_ms"])

    all_agents = set()
    route_buckets = []
    for r in route_rows:
        all_agents.add(r["model_id"])
        route_buckets.append({"hour": r["hour"], "model_id": r["model_id"], "count": r["cnt"]})

    latency_buckets = []
    for (hour, mid), vals in lat_map.items():
        all_agents.add(mid)
        sv = sorted(vals)
        n  = len(sv)
        p50 = sv[int(n * 0.50)]
        p95 = sv[min(int(n * 0.95), n - 1)]
        latency_buckets.append({"hour": hour, "model_id": mid, "p50": p50, "p95": p95})

    latency_buckets.sort(key=lambda x: (x["hour"], x["model_id"]))
    return {
        "route_buckets":   route_buckets,
        "latency_buckets": latency_buckets,
        "agents":          sorted(all_agents),
    }


# ── POST /orchestrator/hosts ─────────────────────────────────────────────────

class AddHostReq(BaseModel):
    id:              str
    name:            str | None = None
    ip:              str        = ""
    type:            str        = "heartbeat"
    mc_agent_url:    str | None = None
    heartbeat_token: str | None = None


@router.post("/hosts", dependencies=[Auth])
def add_host(req: AddHostReq) -> dict:
    _ensure_hosts()
    now = _now()
    with _state_conn() as db:
        row = db.execute("SELECT id FROM hosts WHERE id=?", (req.id,)).fetchone()
        if row:
            raise HTTPException(409, f"Host {req.id!r} already exists")
        db.execute(
            "INSERT INTO hosts (id, name, ip, type, mc_agent_url, heartbeat_token, last_seen, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
            (req.id, req.name or req.id, req.ip, req.type, req.mc_agent_url, req.heartbeat_token or "", now)
        )
        db.commit()
    return {"ok": True, "id": req.id}


# ── POST /orchestrator/models ────────────────────────────────────────────────

class AddModelReq(BaseModel):
    id:           str
    name:         str
    host_id:      str
    accelerator:  str        = ""
    bridge_url:   str | None = None
    port:         int | None = None
    capabilities: list[str]  = []
    notes:        str | None = None


@router.post("/models", dependencies=[Auth])
def add_model_entry(req: AddModelReq) -> dict:
    now = _now()
    mid = req.id if ":" in req.id else f"{req.host_id}:{req.id}"
    placement_j = json.dumps({
        "host_id":     req.host_id,
        "bridge_url":  req.bridge_url,
        "accelerator": req.accelerator,
        "gpus": [],
        "llama_binary": "",
        "launch_args":  "",
    })
    capability_j = json.dumps({
        "specialties":  req.capabilities,
        "tool_calling": "unverified",
    })
    with _state_conn() as db:
        row = db.execute("SELECT id FROM models WHERE id=?", (mid,)).fetchone()
        if row:
            raise HTTPException(409, f"Model {mid!r} already exists")
        db.execute(
            "INSERT INTO models"
            " (id, name, backend, weights_path, placement_json, capability_json,"
            "  role_tags_json, enabled, notes, created_at, updated_at)"
            " VALUES (?, ?, 'heartbeat', '', ?, ?, '[]', 1, ?, ?, ?)",
            (mid, req.name, placement_j, capability_j, req.notes, now, now)
        )
        db.execute(
            "INSERT OR IGNORE INTO agent_pool (model_id, added_at, auto_resume) VALUES (?, ?, 0)",
            (mid, now)
        )
        db.commit()
    return {"ok": True, "id": mid}
