"""Postgres persistence for mc-graph."""
import json, uuid
from datetime import datetime, timezone
from typing import Any, Optional
import asyncpg

class Store:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create_run(self, graph_id: str, trigger: str = "manual",
                         trigger_ref: str | None = None,
                         metadata: dict | None = None) -> str:
        run_id = str(uuid.uuid4())
        await self.pool.execute(
            """INSERT INTO runs (id, graph_id, trigger, trigger_ref, status, metadata)
               VALUES ($1, $2, $3, $4, 'running', $5)""",
            run_id, graph_id, trigger, trigger_ref, json.dumps(metadata or {}))
        return run_id

    async def update_run(self, run_id: str, **kwargs):
        set_clauses, vals, i = [], [], 1
        for k, v in kwargs.items():
            if k in ("gpu_seconds", "metadata"):
                set_clauses.append(f"{k} = ${i}::jsonb")
                v = json.dumps(v)
            else:
                set_clauses.append(f"{k} = ${i}")
            vals.append(v); i += 1
        vals.append(run_id)
        await self.pool.execute(
            f"UPDATE runs SET {', '.join(set_clauses)} WHERE id = ${i}", *vals)

    async def get_run(self, run_id: str) -> Optional[dict]:
        row = await self.pool.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
        return dict(row) if row else None

    async def list_runs(self, limit: int = 50, status: str | None = None) -> list[dict]:
        if status:
            rows = await self.pool.fetch(
                "SELECT * FROM runs WHERE status = $1 ORDER BY started_at DESC LIMIT $2",
                status, limit)
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT $1", limit)
        return [dict(r) for r in rows]

    async def save_checkpoint(self, run_id: str, seq: int, node_id: str,
                               state: dict, diff: dict | None = None):
        await self.pool.execute(
            """INSERT INTO checkpoints (run_id, seq, node_id, state, diff)
               VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
               ON CONFLICT (run_id, seq) DO UPDATE SET state=$4::jsonb, diff=$5::jsonb""",
            run_id, seq, node_id, json.dumps(state), json.dumps(diff) if diff else None)

    async def get_latest_checkpoint(self, run_id: str) -> Optional[dict]:
        row = await self.pool.fetchrow(
            "SELECT * FROM checkpoints WHERE run_id=$1 ORDER BY seq DESC LIMIT 1", run_id)
        return dict(row) if row else None

    async def list_checkpoints(self, run_id: str) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT * FROM checkpoints WHERE run_id=$1 ORDER BY seq", run_id)
        return [dict(r) for r in rows]

    async def start_span(self, run_id: str, node_id: str, node_type: str,
                          name: str, parent_id: str | None = None, **attrs) -> str:
        span_id = str(uuid.uuid4())
        await self.pool.execute(
            """INSERT INTO spans (id, run_id, parent_id, node_id, node_type, name,
                                  started_at, attributes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)""",
            span_id, run_id, parent_id, node_id, node_type, name,
            datetime.now(timezone.utc), json.dumps(attrs))
        return span_id

    async def end_span(self, span_id: str, status: str = "ok", **attrs):
        extra = {}
        for k in ("model_id","tokens_in","tokens_out","tool_name","verdict","contract_line"):
            if k in attrs:
                extra[k] = attrs.pop(k)
        set_clauses = ["ended_at = $2", "status = $3",
                        "attributes = attributes || $4::jsonb"]
        vals: list[Any] = [span_id, datetime.now(timezone.utc), status, json.dumps(attrs)]
        col_i = 5
        for k, v in extra.items():
            if k in ("model_id","tool_name","verdict","contract_line","tokens_in","tokens_out"):
                set_clauses.append(f"{k} = ${col_i}")
                vals.append(v)
                col_i += 1
        await self.pool.execute(
            f"UPDATE spans SET {', '.join(set_clauses)} WHERE id = $1", *vals)

    async def list_spans(self, run_id: str) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT * FROM spans WHERE run_id=$1 ORDER BY started_at", run_id)
        return [dict(r) for r in rows]

    async def create_approval(self, run_id: str, span_id: str, node_id: str,
                               graph_id: str, action_type: str, payload: dict) -> str:
        approval_id = str(uuid.uuid4())
        await self.pool.execute(
            """INSERT INTO approvals (id, run_id, span_id, node_id, graph_id,
                                      action_type, payload, status)
               VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,'pending')""",
            approval_id, run_id, span_id, node_id, graph_id,
            action_type, json.dumps(payload))
        return approval_id

    async def resolve_approval(self, approval_id: str, decision: str,
                                resolved_by: str = "user"):
        await self.pool.execute(
            """UPDATE approvals SET status=$2, resolved_at=now(), resolved_by=$3
               WHERE id=$1""",
            approval_id, decision, resolved_by)

    async def get_approval(self, approval_id: str) -> Optional[dict]:
        row = await self.pool.fetchrow("SELECT * FROM approvals WHERE id=$1", approval_id)
        return dict(row) if row else None

    async def list_approvals(self, status: str = "pending") -> list[dict]:
        rows = await self.pool.fetch(
            """SELECT a.*, r.graph_id, r.current_node
               FROM approvals a JOIN runs r ON r.id=a.run_id
               WHERE a.status=$1 ORDER BY a.created_at""", status)
        return [dict(r) for r in rows]
