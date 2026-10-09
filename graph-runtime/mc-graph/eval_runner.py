#!/usr/bin/env python3
"""mc-graph eval runner: run eval task sets for a graph and record results to Postgres.

Usage:
  python eval_runner.py incident_investigation [--evals-dir /path/to/evals]
  python eval_runner.py a11y_fix
"""
import argparse, asyncio, json, logging, os, sys, time, uuid
from pathlib import Path

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("mc-eval")

MC_GRAPH_URL = os.getenv("MC_GRAPH_URL", "http://localhost:4002")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://mission-control:CHANGE_ME@localhost:30532/mission-control")
EVALS_DIR = Path(os.getenv("EVALS_DIR", "/opt/mc-graph/../evals"))


async def wait_for_run(run_id: str, timeout_s: int = 120) -> dict:
    """Poll mc-graph until run completes or timeout."""
    deadline = time.time() + timeout_s
    async with httpx.AsyncClient(timeout=30) as http:
        while time.time() < deadline:
            r = await http.get(f"{MC_GRAPH_URL}/runs/{run_id}")
            if r.is_success:
                data = r.json()
                run = data.get("run", {})
                if run.get("status") in ("done", "failed", "waiting_approval"):
                    return run
            await asyncio.sleep(3)
    return {"status": "timeout", "id": run_id}


def check_contract(run: dict, state: dict, contract: dict) -> tuple[bool, str | None]:
    """Return (passed, failure_reason)."""
    status_not = contract.get("status_not", [])
    if run.get("status") in status_not:
        return False, f"status {run['status']!r} is in status_not {status_not}"

    for key, expected in (contract.get("state_contains") or {}).items():
        actual = state.get(key)
        if actual != expected:
            return False, f"state[{key!r}] = {actual!r}, expected {expected!r}"

    prop_type = contract.get("proposal_type")
    if prop_type:
        proposal = state.get("proposal") or {}
        if proposal.get("type") != prop_type:
            return False, f"proposal.type = {proposal.get('type')!r}, expected {prop_type!r}"

    return True, None


async def run_eval(graph_id: str, task: dict, pool: asyncpg.Pool) -> dict:
    eval_run_id = None  # set later per task
    start = time.time()
    log.info("  task %s ...", task["id"])

    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(f"{MC_GRAPH_URL}/runs", json={
            "graph_id": graph_id,
            "initial_state": task["initial_state"],
            "trigger": "eval",
            "trigger_ref": task["id"],
        })
        if not r.is_success:
            log.error("  failed to start run: %s", r.text)
            return {"task_id": task["id"], "passed": False, "failure_reason": f"HTTP {r.status_code}",
                    "tokens": 0, "gpu_seconds": 0.0}
        run_id = r.json()["run_id"]

    run = await wait_for_run(run_id)
    elapsed = time.time() - start

    # fetch final state from latest checkpoint
    state: dict = {}
    async with httpx.AsyncClient(timeout=30) as http:
        cr = await http.get(f"{MC_GRAPH_URL}/runs/{run_id}/checkpoints")
        if cr.is_success:
            checkpoints = cr.json()
            if checkpoints:
                state = checkpoints[-1].get("state", {})
        sr = await http.get(f"{MC_GRAPH_URL}/runs/{run_id}/spans")
        spans = sr.json() if sr.is_success else []

    total_tokens = sum(
        (s.get("tokens_in") or 0) + (s.get("tokens_out") or 0)
        for s in spans)

    passed, reason = check_contract(run, state, task.get("contract", {}))
    log.info("  task %s → %s%s (%.1fs, %d tok)",
             task["id"], "PASS" if passed else "FAIL",
             f" [{reason}]" if reason else "", elapsed, total_tokens)

    return {
        "task_id": task["id"],
        "passed": passed,
        "failure_reason": reason,
        "tokens": total_tokens,
        "gpu_seconds": elapsed,
        "run_id": run_id,
    }


async def main(graph_id: str, commit_sha: str | None, triggered_by: str):
    task_file = EVALS_DIR / graph_id / "tasks.json"
    if not task_file.exists():
        log.error("No eval tasks for graph %s at %s", graph_id, task_file)
        sys.exit(1)

    with open(task_file) as f:
        spec = json.load(f)
    tasks = spec["tasks"]
    log.info("Running %d eval tasks for graph=%s", len(tasks), graph_id)

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)

    eval_id = f"eval-{uuid.uuid4().hex[:12]}"
    await pool.execute(
        "INSERT INTO eval_runs (id, graph_id, triggered_by, commit_sha, tasks_total) VALUES ($1,$2,$3,$4,$5)",
        eval_id, graph_id, triggered_by, commit_sha, len(tasks))

    results = []
    for task in tasks:
        result = await run_eval(graph_id, task, pool)
        results.append(result)
        await pool.execute(
            """INSERT INTO eval_task_results (eval_run_id, task_id, passed, tokens, gpu_seconds, run_id, failure_reason)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            eval_id, result["task_id"], result["passed"],
            result["tokens"], result["gpu_seconds"],
            result.get("run_id"), result.get("failure_reason"))

    passed_count = sum(1 for r in results if r["passed"])
    success_rate = passed_count / len(results) if results else 0.0
    avg_tokens = sum(r["tokens"] for r in results) // max(len(results), 1)
    avg_gpu = sum(r["gpu_seconds"] for r in results) / max(len(results), 1)

    await pool.execute(
        """UPDATE eval_runs SET tasks_passed=$2, success_rate=$3, avg_tokens=$4, avg_gpu_seconds=$5
           WHERE id=$1""",
        eval_id, passed_count, success_rate, avg_tokens, avg_gpu)

    await pool.close()

    log.info("Eval complete: %d/%d passed (%.0f%%)", passed_count, len(tasks), success_rate * 100)
    print(json.dumps({
        "eval_run_id": eval_id, "graph_id": graph_id,
        "passed": passed_count, "total": len(tasks),
        "success_rate": success_rate,
    }))
    sys.exit(0 if passed_count == len(tasks) else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("graph_id")
    parser.add_argument("--commit-sha", default=None)
    parser.add_argument("--triggered-by", default="manual")
    parser.add_argument("--evals-dir", default=None)
    args = parser.parse_args()
    if args.evals_dir:
        EVALS_DIR = Path(args.evals_dir)
    asyncio.run(main(args.graph_id, args.commit_sha, args.triggered_by))
