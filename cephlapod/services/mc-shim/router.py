"""
Orchestrator routing: asks the current orchestrator model which agent to use
for a given request. Returns (model_id, reason, latency_ms).
"""
from __future__ import annotations
import datetime, json, time, sqlite3, httpx
from config import MC_AGENT_URL, MC_AGENT_TOKEN, EVENTS_DB, FALLBACK_ORCH_PORT

STATE_DB   = "/var/lib/mission-control/state.db"
STALE_S    = 90


# ── Pool from state.db ────────────────────────────────────────────────────────

def _state_conn() -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(STATE_DB)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _is_online(last_seen: str | None) -> bool:
    if not last_seen:
        return False
    try:
        ts = datetime.datetime.strptime(last_seen, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc
        )
        return (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds() < STALE_S
    except Exception:
        return False


def _local_running_ports() -> dict[str, int]:
    """Ask mc-agent for locally-running model ports."""
    try:
        r = httpx.get(
            f"{MC_AGENT_URL}/models/running",
            headers={"Authorization": f"Bearer {MC_AGENT_TOKEN}"},
            timeout=5,
        )
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def get_pool_from_state_db() -> list[dict]:
    """
    Return a list of agent-pool entries with {model_id, port, bridge_url,
    specialties, tool_calling} for all enabled, reachable pool members.
    Falls back to mc-agent /models/running if state.db is unavailable.
    """
    db = _state_conn()
    if db is None:
        # Fallback: just use whatever mc-agent says is running
        ports = _local_running_ports()
        return [{"model_id": mid, "port": port, "bridge_url": None,
                 "specialties": [], "tool_calling": "unverified"}
                for mid, port in ports.items()]

    # Get enabled pool members
    try:
        pool_ids = {r["model_id"] for r in db.execute(
            "SELECT model_id FROM agent_pool"
        ).fetchall()}
    except Exception:
        pool_ids = set()

    # Check which hosts are online
    online_hosts: set[str] = {"gpuhost"}  # gpuhost is always online
    try:
        for h in db.execute("SELECT id, last_seen FROM hosts").fetchall():
            if _is_online(h["last_seen"]):
                online_hosts.add(h["id"])
    except Exception:
        pass

    # Get locally running models
    local_ports = _local_running_ports()

    agents = []
    try:
        rows = db.execute("SELECT * FROM models WHERE enabled=1").fetchall()
    except Exception:
        rows = []

    for m in rows:
        if m["id"] not in pool_ids:
            continue
        try:
            placement   = json.loads(m["placement_json"])
            capability  = json.loads(m["capability_json"])
        except Exception:
            continue

        host_id    = placement.get("host_id", "gpuhost")
        bridge_url = placement.get("bridge_url")

        if host_id not in online_hosts:
            continue  # host unreachable — skip

        # Determine the port/bridge the shim should forward to
        if bridge_url:
            # Heartbeat host — forward directly to bridge_url
            # We store the bridge_url; the shim uses it instead of 127.0.0.1:port
            try:
                from urllib.parse import urlparse
                port = urlparse(bridge_url).port or 80
            except Exception:
                port = None
        elif m["id"] in local_ports:
            port = local_ports[m["id"]]
            bridge_url = None
        else:
            continue  # not running locally and no bridge_url

        agents.append({
            "model_id":    m["id"],
            "port":        port,
            "bridge_url":  bridge_url,  # None = use 127.0.0.1:port; str = use directly
            "specialties": capability.get("specialties", []),
            "tool_calling": capability.get("tool_calling", "unverified"),
            "param_count": capability.get("param_count"),
            "ctx_len":     capability.get("ctx_len"),
        })

    return agents


def get_orchestrator_from_state_db() -> tuple[str | None, str | None]:
    """Return (model_id, forward_url) for the current orchestrator."""
    db = _state_conn()
    if db is None:
        return None, f"http://127.0.0.1:{FALLBACK_ORCH_PORT}"

    try:
        row = db.execute("SELECT model_id FROM orchestrator_slot WHERE id=1").fetchone()
        orch_id = row["model_id"] if row else None
    except Exception:
        orch_id = None

    if not orch_id:
        return None, f"http://127.0.0.1:{FALLBACK_ORCH_PORT}"

    # Find that model's forward URL
    try:
        mrow = db.execute("SELECT placement_json FROM models WHERE id=?", (orch_id,)).fetchone()
        if mrow:
            placement  = json.loads(mrow["placement_json"])
            bridge_url = placement.get("bridge_url")
            if bridge_url:
                return orch_id, bridge_url
    except Exception:
        pass

    # Fallback: check local running
    local_ports = _local_running_ports()
    if orch_id in local_ports:
        return orch_id, f"http://127.0.0.1:{local_ports[orch_id]}"

    return orch_id, f"http://127.0.0.1:{FALLBACK_ORCH_PORT}"


# ── Routing prompt ────────────────────────────────────────────────────────────

_ROUTING_SYSTEM = """\
You are a routing orchestrator. Given the user's request and the available agents \
with their capabilities, select the best agent. Respond with JSON only — \
no prose, no markdown, just the JSON object.

Format:
{"model_id": "<id>", "reason": "<one sentence explaining why this agent fits>"}
"""


def _build_routing_prompt(user_summary: str, agents: list[dict]) -> str:
    agent_lines = "\n".join(
        f'- {a["model_id"]} (specialties: {", ".join(a.get("specialties", [])) or "general"},'
        f' tool_calling: {a.get("tool_calling", "unverified")},'
        f' params: {a.get("param_count", "?")}, ctx: {a.get("ctx_len", "?")})'
        for a in agents
    )
    return (
        f"Available agents:\n{agent_lines}\n\n"
        f"User request: {user_summary}\n\n"
        "Select the best agent."
    )


# ── Route ─────────────────────────────────────────────────────────────────────

def route(
    user_messages: list[dict],
    available_agents: list[dict],
    session_id: str,
) -> tuple[str | None, str, int]:
    """
    Ask orchestrator to pick an agent.
    Returns (model_id, reason, latency_ms).
    Falls back to first available agent on error.
    """
    import event_log

    last_user = next(
        (m for m in reversed(user_messages) if m.get("role") == "user"), {}
    )
    content = last_user.get("content", "")
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    summary = content[:500]

    orch_model_id, orch_url = get_orchestrator_from_state_db()

    if not orch_url or not available_agents:
        reason = "no orchestrator or agents available — passthrough"
        event_log.log(session_id, "agent_selected", {
            "model_id": None, "reason": reason, "fallback": True,
        })
        return None, reason, 0

    routing_prompt = _build_routing_prompt(summary, available_agents)
    t0 = time.monotonic()

    try:
        resp = httpx.post(
            f"{orch_url}/v1/chat/completions",
            json={
                "model": "local",
                "messages": [
                    {"role": "system",  "content": _ROUTING_SYSTEM},
                    {"role": "user",    "content": routing_prompt},
                ],
                "max_tokens": 256,
                "temperature": 0.0,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=30,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        raw    = resp.json()
        answer = raw["choices"][0]["message"]["content"].strip()

        event_log.log(session_id, "orchestrator_plan", {
            "orchestrator_model_id": orch_model_id,
            "routing_prompt": routing_prompt,
            "raw_response": answer,
            "latency_ms": latency_ms,
        })

        try:
            parsed   = json.loads(answer)
            model_id = parsed.get("model_id")
            reason   = parsed.get("reason", "")
        except json.JSONDecodeError:
            import re
            m = re.search(r'\{[^}]+\}', answer, re.DOTALL)
            if m:
                parsed   = json.loads(m.group())
                model_id = parsed.get("model_id")
                reason   = parsed.get("reason", "")
            else:
                model_id = None
                reason   = f"orchestrator returned unparseable response: {answer[:100]}"

        event_log.log(session_id, "agent_selected", {
            "model_id": model_id, "reason": reason, "latency_ms": latency_ms,
        })
        return model_id, reason, latency_ms

    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        reason     = f"orchestrator error: {e}"
        event_log.log(session_id, "error", {
            "phase": "orchestration", "message": str(e), "latency_ms": latency_ms,
        })
        fallback = available_agents[0]["model_id"] if available_agents else None
        event_log.log(session_id, "agent_selected", {
            "model_id": fallback, "reason": reason, "fallback": True,
        })
        return fallback, reason, latency_ms
