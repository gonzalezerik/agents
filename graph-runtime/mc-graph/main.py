"""mc-graph: Graph execution runtime for mission-control."""
import asyncio, json, logging, os
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engine import GraphEngine
from store import Store
from graphs.incident_investigation import get_graph as get_incident_graph

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mc-graph")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://mission-control:CHANGE_ME"
    "@mission-control-db-rw.mission-control.svc.cluster.local:5432/mission-control")

_pool = None
_engine = None

GRAPHS = {
    "incident_investigation": get_incident_graph(),
}

@asynccontextmanager
async def lifespan(app):
    global _pool, _engine
    log.info("Connecting to Postgres: %s", DATABASE_URL.split("@")[-1])
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    _engine = GraphEngine(_pool)
    log.info("mc-graph ready")
    yield
    if _pool:
        await _pool.close()

app = FastAPI(title="mc-graph", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

def engine():
    if _engine is None:
        raise HTTPException(503, "Engine not ready")
    return _engine

def store():
    if _pool is None:
        raise HTTPException(503, "DB not ready")
    return Store(_pool)


class StartRunRequest(BaseModel):
    graph_id: str
    initial_state: dict = {}
    trigger: str = "manual"
    trigger_ref: str | None = None

@app.post("/runs", status_code=201)
async def start_run(req: StartRunRequest):
    graph = GRAPHS.get(req.graph_id)
    if not graph:
        raise HTTPException(404, f"Graph not found: {req.graph_id}")
    run_id = await engine().start_run(
        graph, req.initial_state, trigger=req.trigger, trigger_ref=req.trigger_ref)
    return {"run_id": run_id, "graph_id": req.graph_id}

@app.get("/runs")
async def list_runs(limit: int = 50, status: str | None = None):
    return await store().list_runs(limit, status)

@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = await store().get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run not found: {run_id}")
    chk = await store().get_latest_checkpoint(run_id)
    spans = await store().list_spans(run_id)
    return {"run": run, "latest_checkpoint": chk, "spans": spans}

@app.get("/runs/{run_id}/checkpoints")
async def list_checkpoints(run_id: str):
    return await store().list_checkpoints(run_id)

@app.get("/runs/{run_id}/spans")
async def list_spans(run_id: str):
    return await store().list_spans(run_id)

@app.get("/approvals")
async def list_approvals(status: str = "pending"):
    return await store().list_approvals(status)

@app.get("/approvals/{approval_id}")
async def get_approval(approval_id: str):
    a = await store().get_approval(approval_id)
    if not a:
        raise HTTPException(404, "Approval not found")
    return a

class ApprovalDecision(BaseModel):
    decision: str
    resolved_by: str = "user"

@app.post("/approvals/{approval_id}/decide")
async def decide_approval(approval_id: str, req: ApprovalDecision):
    a = await store().get_approval(approval_id)
    if not a:
        raise HTTPException(404, "Approval not found")
    if a["status"] != "pending":
        raise HTTPException(409, f"Approval already {a['status']}")
    graph = GRAPHS.get(a["graph_id"])
    if not graph:
        raise HTTPException(404, f"Graph {a['graph_id']} not found")
    await engine().approve(approval_id, req.decision, graph, req.resolved_by)
    return {"approval_id": approval_id, "decision": req.decision}

@app.get("/graphs")
async def list_graphs():
    return [
        {"id": g["id"], "display_name": g.get("display_name", g["id"]),
         "description": g.get("description",""), "nodes": list(g["nodes"].keys())}
        for g in GRAPHS.values()
    ]

@app.get("/graphs/{graph_id}")
async def get_graph_def(graph_id: str):
    g = GRAPHS.get(graph_id)
    if not g:
        raise HTTPException(404)
    return g

@app.get("/health")
async def health():
    return {"status": "ok", "graphs": list(GRAPHS.keys())}
