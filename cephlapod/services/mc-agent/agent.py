"""
mc-agent — FastAPI HTTP agent for gpuhost (and llmhost-llm).
Exposes GPU state, model lifecycle, and shim session control.
Bearer token auth on all routes.
"""
from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Annotated

import gpu as gpu_mod
import launcher
from config import TOKEN, HOST_ID

app = FastAPI(title="mc-agent", version="0.1.0")

VERSION = "0.1.0"


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_auth(authorization: Annotated[str | None, Header()] = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if authorization.removeprefix("Bearer ") != TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


Auth = Depends(require_auth)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True, "version": VERSION, "host_id": HOST_ID}


# ── Observed state ────────────────────────────────────────────────────────────

@app.get("/state", dependencies=[Auth])
def state():
    managed = launcher.managed_pids()
    return {
        "host_id": HOST_ID,
        "polled_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "reachable": True,
        "gpus": gpu_mod.gpu_state(managed),
        "running_models": launcher.running_models(),
        "agent_version": VERSION,
    }


# ── Model lifecycle ───────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    model_id: str

class StopRequest(BaseModel):
    model_id: str
    reason: str = ""


@app.post("/models/start", dependencies=[Auth])
def models_start(req: StartRequest):
    try:
        pid = launcher.start(req.model_id)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"pid": pid}


@app.post("/models/stop", dependencies=[Auth])
def models_stop(req: StopRequest):
    found = launcher.stop(req.model_id, req.reason)
    if not found:
        raise HTTPException(status_code=404, detail=f"Model {req.model_id!r} not running")
    return {"ok": True}


# ── Shim session passthrough ──────────────────────────────────────────────────

class PassthroughRequest(BaseModel):
    session_id: str
    enabled: bool

# In-memory: shim reads this dict directly when running in the same process
_passthrough: dict[str, bool] = {}

@app.post("/shim/passthrough", dependencies=[Auth])
def set_passthrough(req: PassthroughRequest):
    _passthrough[req.session_id] = req.enabled
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    from config import PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT)
