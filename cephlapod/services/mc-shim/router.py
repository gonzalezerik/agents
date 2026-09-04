"""
Orchestrator routing: asks the current orchestrator model which agent to use
for a given request. Returns (model_id, reason, latency_ms).

The routing prompt is minimal and structured — we ask for JSON only.
"""
from __future__ import annotations
import json, time, sqlite3, httpx
from config import MC_AGENT_URL, MC_AGENT_TOKEN, EVENTS_DB, FALLBACK_ORCH_PORT


# ── Resolve orchestrator model + port ─────────────────────────────────────────

def _get_orchestrator_info() -> tuple[str | None, int | None]:
    """
    Read current orchestrator slot from the shared SQLite,
    then ask mc-agent for its port.
    Returns (model_id, port) or (None, None).
    """
    try:
        conn = sqlite3.connect(EVENTS_DB.replace("events.db", "") + "../mission-control/state.db")
    except Exception:
        pass

    # Try mc-agent /models/running
    try:
        r = httpx.get(
            f"{MC_AGENT_URL}/models/running",
            headers={"Authorization": f"Bearer {MC_AGENT_TOKEN}"},
            timeout=5,
        )
        if r.status_code == 200:
            running = r.json()  # {model_id: port}
            # Read desired orchestrator from SQLite
            try:
                db = sqlite3.connect(EVENTS_DB)
                row = db.execute("SELECT orchestrator_model_id FROM sessions ORDER BY last_seen DESC LIMIT 1").fetchone()
                if row and row[0] and row[0] in running:
                    return row[0], running[row[0]]
            except Exception:
                pass
            # Fall back to any running orchestrator-eligible model
            if running:
                first = next(iter(running.items()))
                return first[0], first[1]
    except Exception:
        pass

    return None, FALLBACK_ORCH_PORT


def _get_agent_pool_info() -> list[dict]:
    """Return list of running agent pool models with capabilities."""
    try:
        r = httpx.get(
            f"{MC_AGENT_URL}/models/running",
            headers={"Authorization": f"Bearer {MC_AGENT_TOKEN}"},
            timeout=5,
        )
        if r.status_code == 200:
            return [{"model_id": mid, "port": port} for mid, port in r.json().items()]
    except Exception:
        pass
    return []


# ── Routing prompt ────────────────────────────────────────────────────────────

_ROUTING_SYSTEM = """\
You are a routing orchestrator. Given the user's request, select the best agent \
from the available pool based on capability fit. Respond with JSON only — \
no prose, no markdown, just the JSON object.

Format:
{"model_id": "<id>", "reason": "<one sentence explaining why this agent fits>"}
"""


def _build_routing_prompt(user_summary: str, agents: list[dict]) -> str:
    agent_lines = "\n".join(
        f'- {a["model_id"]} (specialties: {", ".join(a.get("specialties", []))},'
        f' tool_calling: {a.get("tool_calling", "unverified")})'
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

    # Summarise the last user message (don't send full history to orchestrator)
    last_user = next(
        (m for m in reversed(user_messages) if m.get("role") == "user"), {}
    )
    content = last_user.get("content", "")
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    summary = content[:500]

    orch_model_id, orch_port = _get_orchestrator_info()

    if not orch_port or not available_agents:
        reason = "no orchestrator or agents available — passthrough"
        event_log.log(session_id, "agent_selected", {
            "model_id": None, "reason": reason, "fallback": True,
        })
        return None, reason, 0

    routing_prompt = _build_routing_prompt(summary, available_agents)
    t0 = time.monotonic()

    try:
        resp = httpx.post(
            f"http://127.0.0.1:{orch_port}/v1/chat/completions",
            json={
                "model": "local",
                "messages": [
                    {"role": "system", "content": _ROUTING_SYSTEM},
                    {"role": "user", "content": routing_prompt},
                ],
                "max_tokens": 256,
                "temperature": 0.0,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=30,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        raw = resp.json()
        answer = raw["choices"][0]["message"]["content"].strip()

        event_log.log(session_id, "orchestrator_plan", {
            "orchestrator_model_id": orch_model_id,
            "routing_prompt": routing_prompt,
            "raw_response": answer,
            "latency_ms": latency_ms,
        })

        # Parse JSON response
        try:
            parsed = json.loads(answer)
            model_id = parsed.get("model_id")
            reason = parsed.get("reason", "")
        except json.JSONDecodeError:
            # Try to extract JSON from text
            import re
            m = re.search(r'\{[^}]+\}', answer, re.DOTALL)
            if m:
                parsed = json.loads(m.group())
                model_id = parsed.get("model_id")
                reason = parsed.get("reason", "")
            else:
                model_id = None
                reason = f"orchestrator returned unparseable response: {answer[:100]}"

        event_log.log(session_id, "agent_selected", {
            "model_id": model_id,
            "reason": reason,
            "latency_ms": latency_ms,
        })
        return model_id, reason, latency_ms

    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        reason = f"orchestrator error: {e}"
        event_log.log(session_id, "error", {
            "phase": "orchestration", "message": str(e), "latency_ms": latency_ms,
        })
        # Fall back to first agent
        fallback = available_agents[0]["model_id"] if available_agents else None
        event_log.log(session_id, "agent_selected", {
            "model_id": fallback, "reason": reason, "fallback": True,
        })
        return fallback, reason, latency_ms
