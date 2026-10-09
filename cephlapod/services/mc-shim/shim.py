"""
mc-shim: Anthropic Messages API shim on gpuhost.
Claude Code connects here; shim orchestrates routing and streams back.

Flow:
  1. Request arrives at POST /v1/messages
  2. If passthrough mode → forward directly to last-used agent port
  3. Else → orchestrator selects agent → forward to agent → stream back
  4. Every event (prompt, plan, tool_call, tool_result, response, error) is logged

Endpoint for Claude Code:  http://localhost:4000
Model string to configure:  any string (shim ignores it, routes internally)
"""
from __future__ import annotations
import asyncio, json, time, uuid, httpx
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from typing import Annotated, Any, AsyncIterator

import event_log
import router as routing
import translator
import tool_repair
from config import TOKEN, PORT, MC_AGENT_URL, MC_AGENT_TOKEN

app = FastAPI(title="mc-shim", version="0.1.0")

VERSION = "0.1.0"


# ── Auth ──────────────────────────────────────────────────────────────────────

def _check_auth(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    if authorization.removeprefix("Bearer ") != TOKEN:
        raise HTTPException(403, "Invalid token")


# ── mc-agent helpers ──────────────────────────────────────────────────────────

async def _running_models() -> dict[str, int]:
    """Return {model_id: port} for all currently running models."""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(
                f"{MC_AGENT_URL}/models/running",
                headers={"Authorization": f"Bearer {MC_AGENT_TOKEN}"},
                timeout=5,
            )
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}


def _get_pool() -> list[dict]:
    """Return the full routing pool from state.db (includes heartbeat hosts)."""
    try:
        import router as routing_mod
        return routing_mod.get_pool_from_state_db()
    except Exception:
        return []


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _keepalive_pings(interval: float = 20.0) -> AsyncIterator[str]:
    """Yield SSE pings periodically to keep the connection alive."""
    while True:
        await asyncio.sleep(interval)
        yield _sse("ping", {"type": "ping"})


# ── Main stream handler ───────────────────────────────────────────────────────

async def _stream_response(
    session_id: str,
    agent_base: str,
    agent_model_id: str,
    oai_body: dict[str, Any],
    anthropic_body: dict[str, Any],
    message_id: str,
    input_tokens_est: int,
) -> AsyncIterator[str]:
    """Core streaming: forward to agent, translate SSE events, log everything."""

    # message_start
    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": agent_model_id,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens_est, "output_tokens": 0},
        },
    })
    yield _sse("ping", {"type": "ping"})

    stream_state: dict[str, Any] = {}
    t0 = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{agent_base}/v1/chat/completions",
                json=oai_body,
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(f"Agent returned {resp.status_code}: {body[:200]}")

                async for raw_line in resp.aiter_lines():
                    if not raw_line.startswith("data:"):
                        continue
                    data_str = raw_line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    for evt_name, evt_data in translator.chunk_to_anthropic_events(chunk, stream_state):
                        yield _sse(evt_name, evt_data)

    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        event_log.log(session_id, "error", {
            "phase": "agent_stream", "message": str(e), "latency_ms": latency_ms,
        })
        yield _sse("error", {"type": "error", "error": {"type": "api_error", "message": str(e)}})
        return

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Extract full content, repair tool blocks, log
    content_blocks = translator.extract_content_blocks(stream_state)
    repaired_blocks, repairs = tool_repair.repair_tool_blocks(content_blocks, session_id)

    for rep in repairs:
        event_log.log(session_id, "repair", rep)

    usage = stream_state.get("finish_usage", {})
    event_log.log(session_id, "agent_response", {
        "model_id": agent_model_id,
        "content_blocks": repaired_blocks,
        "stop_reason": stream_state.get("stop_reason", "end_turn"),
        "tokens_in": usage.get("prompt_tokens"),
        "tokens_out": usage.get("completion_tokens"),
        "latency_ms": latency_ms,
    })

    event_log.log(session_id, "final_response", {
        "stop_reason": stream_state.get("stop_reason", "end_turn"),
        "total_latency_ms": latency_ms,
        "had_repairs": len(repairs) > 0,
    })


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True, "version": VERSION, "service": "mc-shim"}


@app.post("/v1/messages")
async def messages(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    _check_auth(authorization)

    body: dict[str, Any] = await request.json()
    client_ip = request.client.host if request.client else "unknown"

    # Resolve or create session — X-Session-Id header, else derive from client
    session_id = request.headers.get("X-Session-Id") or f"sess-{client_ip}-{uuid.uuid4().hex[:8]}"
    message_id = f"msg_{uuid.uuid4().hex[:24]}"

    event_log.ensure_session(session_id, client_ip=client_ip)
    event_log.increment_request_count(session_id)

    messages_list: list[dict] = body.get("messages", [])

    # Set session title from first user message
    first_user = next((m for m in messages_list if m.get("role") == "user"), None)
    if first_user:
        content = first_user.get("content", "")
        if isinstance(content, list):
            content = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
        event_log.set_session_title(session_id, str(content)[:120])

    # Log the full incoming request
    event_log.log(session_id, "user_message", {
        "messages": messages_list,
        "model_requested": body.get("model"),
        "max_tokens": body.get("max_tokens"),
        "tools": body.get("tools", []),
        "system": body.get("system", ""),
        "stream": body.get("stream", True),
    })

    # Rough input token estimate (4 chars ≈ 1 token)
    raw_text = json.dumps(messages_list)
    input_tokens_est = len(raw_text) // 4

    # Check passthrough
    passthrough_sessions: dict[str, bool] = app.state.passthrough if hasattr(app.state, "passthrough") else {}
    is_passthrough = passthrough_sessions.get(session_id, False)

    running = await _running_models()

    if is_passthrough or not running:
        # Direct forward — use pinned model_id if one was specified
        passthrough_models: dict[str, str] = app.state.passthrough_models if hasattr(app.state, "passthrough_models") else {}
        target_mid = passthrough_models.get(session_id) if is_passthrough else None
        # Try pool first (supports heartbeat hosts)
        pool_all = _get_pool()
        chosen_pass = next((a for a in pool_all if a["model_id"] == target_mid), None) if target_mid else None
        if chosen_pass:
            agent_bridge = chosen_pass.get("bridge_url")
            agent_port   = chosen_pass.get("port", FALLBACK_ORCH_PORT)
            agent_model_id = chosen_pass["model_id"]
        elif running:
            fallback_model_id, fallback_port = next(iter(running.items()))
            agent_model_id = fallback_model_id
            agent_bridge   = None
            agent_port     = fallback_port
        else:
            raise HTTPException(503, "No models running")
        event_log.log(session_id, "passthrough_forward", {
            "model_id": agent_model_id, "port": agent_port,
            "reason": "passthrough mode" if is_passthrough else "no orchestrator",
        })
        oai_body = translator.anthropic_to_openai({**body, "stream": True})
    else:
        # Build agent list from state.db (includes heartbeat hosts like laptop)
        pool = _get_pool()
        if not pool:
            pool = [{"model_id": mid, "port": port, "bridge_url": None,
                     "specialties": [], "tool_calling": "unverified"}
                    for mid, port in running.items()]

        chosen_id, reason, plan_latency = routing.route(messages_list, pool, session_id)

        chosen_entry = next((a for a in pool if a["model_id"] == chosen_id), None)
        if not chosen_entry:
            if not pool:
                raise HTTPException(503, "No models in pool")
            chosen_entry = pool[0]
            chosen_id = chosen_entry["model_id"]
        agent_bridge = chosen_entry.get("bridge_url")
        agent_port   = chosen_entry.get("port", FALLBACK_ORCH_PORT)
        agent_model_id = chosen_id
        oai_body = translator.anthropic_to_openai({**body, "stream": True})

    async def event_stream():
        async for chunk in _stream_response(
            session_id, agent_bridge or f"http://127.0.0.1:{agent_port}", agent_model_id,
            oai_body, body, message_id, input_tokens_est,
        ):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Session-Id": session_id,
            "X-Message-Id": message_id,
        },
    )


# ── Passthrough toggle (from mc-agent) ────────────────────────────────────────

from pydantic import BaseModel

class PassthroughReq(BaseModel):
    session_id: str
    enabled: bool
    model_id: str | None = None

@app.post("/shim/passthrough")
def set_passthrough(req: PassthroughReq, authorization: Annotated[str | None, Header()] = None):
    _check_auth(authorization)
    if not hasattr(app.state, "passthrough"):
        app.state.passthrough = {}
    if not hasattr(app.state, "passthrough_models"):
        app.state.passthrough_models = {}
    app.state.passthrough[req.session_id] = req.enabled
    if req.model_id is not None:
        if req.enabled:
            app.state.passthrough_models[req.session_id] = req.model_id
        else:
            app.state.passthrough_models.pop(req.session_id, None)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
