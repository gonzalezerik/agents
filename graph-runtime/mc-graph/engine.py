"""GraphEngine: executes typed node graphs with checkpointing and interrupt support."""
import asyncio, json, logging, re
from typing import Any, Optional
import asyncpg

from store import Store
from tools import (
    k8s_gather_context, k8s_restart_pod, k8s_check_pod_health, llm_call,
    forgejo_fetch_source, forgejo_commit_patch, forgejo_trigger_build,
    k8s_rollout_deployment, k8s_check_deployment_ready,
    notify_reporter, studio_generate, studio_evaluate,
)

def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


log = logging.getLogger("mc-graph.engine")

_waiting: dict[str, asyncio.Event] = {}
_decisions: dict[str, str] = {}
_tasks: dict[str, asyncio.Task] = {}


class InterruptException(Exception):
    def __init__(self, approval_id: str):
        self.approval_id = approval_id


class GraphEngine:
    def __init__(self, pool: asyncpg.Pool):
        self.store = Store(pool)

    async def start_run(self, graph: dict, initial_state: dict,
                         trigger: str = "manual", trigger_ref: str | None = None) -> str:
        run_id = await self.store.create_run(
            graph["id"], trigger=trigger, trigger_ref=trigger_ref)
        task = asyncio.create_task(self._execute(run_id, graph, initial_state))
        _tasks[run_id] = task
        return run_id

    async def resume_run(self, run_id: str, graph: dict):
        task = asyncio.create_task(
            self._execute(run_id, graph, initial_state=None, resume=True))
        _tasks[run_id] = task

    async def approve(self, approval_id: str, decision: str,
                       graph: dict, resolved_by: str = "user"):
        await self.store.resolve_approval(approval_id, decision, resolved_by)
        _decisions[approval_id] = decision
        approval = await self.store.get_approval(approval_id)
        if approval:
            run_id = approval["run_id"]
            ev = _waiting.get(run_id)
            if ev:
                ev.set()
            else:
                await self.resume_run(run_id, graph)

    async def _execute(self, run_id: str, graph: dict,
                        initial_state: dict | None, resume: bool = False):
        nodes = graph["nodes"]
        edges = graph["edges"]
        checkpoint_seq = 0

        if resume:
            chk = await self.store.get_latest_checkpoint(run_id)
            if chk:
                state = dict(chk["state"]) if isinstance(chk["state"], dict) else json.loads(chk["state"])
                checkpoint_seq = chk["seq"]
                last_node = chk["node_id"]
                next_node = self._next_after(last_node, state, edges, nodes)
            else:
                state = {}
                next_node = graph["entry"]
        else:
            state = dict(initial_state or {})
            next_node = graph["entry"]
            await self.store.save_checkpoint(run_id, 0, "START", state)

        try:
            await self._run_from(run_id, graph, state, next_node,
                                  checkpoint_seq, nodes, edges)
        except InterruptException as e:
            log.info("Run %s interrupted at approval %s", run_id, e.approval_id)
        except Exception as exc:
            log.error("Run %s failed: %s", run_id, exc, exc_info=True)
            await self.store.update_run(run_id, status="failed", ended_at=_now())
        finally:
            _tasks.pop(run_id, None)

    async def _run_from(self, run_id: str, graph: dict, state: dict,
                         next_node: str, checkpoint_seq: int, nodes: dict, edges: list):
        while next_node and next_node != "END":
            node = nodes[next_node]
            node_id = next_node
            log.info("Run %s -> node %s (%s)", run_id, node_id, node["type"])
            await self.store.update_run(run_id, current_node=node_id)
            span_id = await self.store.start_span(
                run_id, node_id, node["type"], node.get("display", node_id))
            result_patch: dict = {}
            branch: str | None = None
            try:
                result_patch, branch = await self._exec_node(
                    run_id, node_id, node, state, span_id, graph["id"])
                state = {**state, **result_patch}
                await self.store.end_span(span_id, "ok")
            except InterruptException:
                await self.store.end_span(span_id, "interrupted")
                await self.store.update_run(run_id, status="waiting_approval")
                raise
            except Exception as exc:
                await self.store.end_span(span_id, "error")
                raise
            checkpoint_seq += 1
            await self.store.save_checkpoint(run_id, checkpoint_seq, node_id, state)
            next_node = self._resolve_next(node_id, branch, edges)
        if next_node == "END":
            run = await self.store.get_run(run_id)
            if run and run["status"] not in ("failed",):
                await self.store.update_run(run_id, status="done", ended_at=_now())
            log.info("Run %s completed", run_id)

    async def _exec_node(self, run_id: str, node_id: str, node: dict,
                          state: dict, span_id: str, graph_id: str) -> tuple[dict, str | None]:
        t = node["type"]
        if t == "tool":
            return await self._exec_tool(node, state, span_id)
        elif t == "llm":
            return await self._exec_llm(node, state, span_id)
        elif t == "router":
            branch = await self._exec_router(node, state)
            return {}, branch
        elif t == "human":
            await self._exec_human(run_id, node_id, node, state, span_id, graph_id)
            return {}, None
        elif t == "evaluator":
            return await self._exec_evaluator(node, state, span_id)
        raise ValueError(f"Unknown node type: {t}")

    async def _exec_tool(self, node: dict, state: dict, span_id: str) -> tuple[dict, None]:
        tool_name = node["tool"]
        output_key = node.get("output_key", "result")

        if tool_name == "k8s_gather_context":
            alert = state.get("alert", {})
            pod = alert.get("pod") or alert.get("pod_name")
            ns = alert.get("namespace", "mission-control")
            result = await k8s_gather_context(pod, ns)
        elif tool_name == "k8s_restart_pod":
            proposal = state.get("proposal", {})
            result = await k8s_restart_pod(
                proposal.get("pod", ""), proposal.get("namespace", "mission-control"))
        elif tool_name == "k8s_rollout_deployment":
            result = await k8s_rollout_deployment(**state)
        elif tool_name == "forgejo_fetch_source":
            audit = state.get("audit_result", {}) or {}
            element = audit.get("affected_element", "")
            # try to infer a file path from the audit result; default to globals.css
            file_path = state.get("source_file", "app/globals.css")
            result = await forgejo_fetch_source(file_path)
        elif tool_name == "forgejo_commit_patch":
            patch = state.get("patch", {}) or {}
            result = await forgejo_commit_patch(
                file=patch.get("file", ""),
                diff=patch.get("diff", ""),
                explanation=patch.get("explanation", "a11y fix"),
            )
        elif tool_name == "forgejo_trigger_build":
            result = await forgejo_trigger_build()
        elif tool_name == "notify_reporter":
            result = await notify_reporter(
                report_id=state.get("report_id"),
                verdict=state.get("verdict"),
                commit_result=state.get("commit_result"),
            )
        elif tool_name == "studio_generate":
            result = await studio_generate(
                prompt=state.get("prompt", ""),
                parameters=state.get("parameters"),
            )
        elif tool_name == "studio_evaluate":
            result = await studio_evaluate(generated=state.get("generated"))
        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        await self.store.end_span(span_id, "ok", tool_name=tool_name)
        return {output_key: result}, None

    async def _exec_llm(self, node: dict, state: dict, span_id: str) -> tuple[dict, None]:
        sys_prompt = node.get("system_prompt", "You are a helpful assistant.")
        user_msg = _render_context(state)
        text, tok_in, tok_out = await llm_call(
            sys_prompt, user_msg, model=node.get("model", "auto"),
            max_tokens=node.get("max_tokens", 2000))
        await self.store.end_span(span_id, "ok",
                                   model_id=node.get("model","auto"),
                                   tokens_in=tok_in, tokens_out=tok_out)
        output_key = node.get("output_key", "analysis")
        parsed = _try_parse_json(text)
        if parsed and "proposal" in parsed:
            proposal = parsed.get("proposal") or {}
            return {output_key: text, "proposal": proposal,
                    "_classification": parsed.get("classification","note")}, None
        return {output_key: text}, None

    async def _exec_router(self, node: dict, state: dict) -> str:
        field = node.get("field", "classification")
        branches = node.get("branches", [])
        value = state.get("_classification") or state.get(field, "")
        if not value:
            analysis = state.get("analysis", "")
            parsed = _try_parse_json(analysis)
            if parsed:
                value = parsed.get("classification", "note")
        value = str(value).lower()
        for b in branches:
            if value == b or value.startswith(b):
                return b
        return branches[-1] if branches else "END"

    async def _exec_human(self, run_id: str, node_id: str, node: dict,
                           state: dict, span_id: str, graph_id: str):
        action_type = node.get("action_type", "generic")
        proposal = state.get("proposal", {})
        payload = {**proposal, "state_summary": {
            k: v for k, v in state.items()
            if k not in ("context",) and not str(v).startswith("[LLM")
        }}
        approval_id = await self.store.create_approval(
            run_id, span_id, node_id, graph_id, action_type, payload)
        log.info("Run %s waiting for approval %s", run_id, approval_id)
        ev = asyncio.Event()
        _waiting[run_id] = ev
        try:
            await asyncio.wait_for(ev.wait(), timeout=86400)
        except asyncio.TimeoutError:
            _waiting.pop(run_id, None)
            await self.store.resolve_approval(approval_id, "timeout")
            raise InterruptException(approval_id)
        _waiting.pop(run_id, None)
        decision = _decisions.pop(approval_id, "approved")
        if decision != "approved":
            await self.store.update_run(run_id, status="failed", ended_at=_now())
        raise InterruptException(approval_id)

    async def _exec_evaluator(self, node: dict, state: dict,
                               span_id: str) -> tuple[dict, None]:
        contract = node.get("contract", {})
        must = contract.get("must", [])
        must_not = contract.get("must_not", [])
        output_key = node.get("output_key", "verdict")
        verdict = "pass"
        failed_contract = None
        health: dict = {}

        # pod health checks (incident_investigation)
        if any(c in ("pod_running",) for c in must) or any(c == "crash_loop" for c in must_not):
            proposal = state.get("proposal", {})
            pod = proposal.get("pod", "")
            ns = proposal.get("namespace", "mission-control")
            health = await k8s_check_pod_health(pod, ns)
            for check in must:
                if check == "pod_running" and not health.get("ready", False):
                    verdict = "fail"; failed_contract = f"must: {check}"
            for check in must_not:
                if check == "crash_loop" and health.get("restarts", 0) > 3:
                    verdict = "fail"; failed_contract = f"must_not: {check}"

        # deployment health checks (a11y_fix)
        if any(c == "deployment_ready" for c in must):
            rollout = state.get("rollout_result", {}) or {}
            dep = rollout.get("deployment", "mission-control-app")
            ns = rollout.get("namespace", "mission-control")
            dep_health = await k8s_check_deployment_ready(dep, ns)
            health.update(dep_health)
            for check in must:
                if check == "deployment_ready" and not dep_health.get("deployment_ready", False):
                    verdict = "fail"; failed_contract = f"must: {check}"
            for check in must_not:
                if check == "crash_loop" and dep_health.get("crash_loop", False):
                    verdict = "fail"; failed_contract = f"must_not: {check}"

        # studio/generator_evaluator checks
        if any(c in ("output_valid", "no_errors") for c in must):
            generated = state.get("generated", {}) or {}
            if not generated or generated.get("error"):
                verdict = "fail"; failed_contract = "must: output_valid"
            retry_count = state.get("retry_count", 0) or 0
            if verdict == "fail" and retry_count < 3:
                verdict = "retry"

        await self.store.end_span(span_id, "ok", verdict=verdict, contract_line=failed_contract)
        return {output_key: verdict, "_eval_health": health}, verdict

    def _resolve_next(self, from_node: str, branch: str | None, edges: list) -> str:
        for edge in edges:
            if edge["from"] != from_node:
                continue
            if "branch" in edge:
                if branch and edge["branch"] == branch:
                    return edge["to"]
            else:
                return edge["to"]
        return "END"

    def _next_after(self, node_id: str, state: dict, edges: list, nodes: dict) -> str:
        node = nodes.get(node_id, {})
        if node.get("type") == "human":
            gates = node.get("gates", [])
            for g in gates:
                if g in nodes:
                    return g
        return self._resolve_next(node_id, None, edges)


def _render_context(state: dict) -> str:
    parts = []
    if "alert" in state:
        parts.append(f"ALERT:\n{json.dumps(state['alert'], indent=2)}")
    if "context" in state:
        ctx = state["context"]
        if isinstance(ctx, dict):
            parts.append(f"KUBERNETES CONTEXT:\n{json.dumps(ctx, indent=2)}")
    if "analysis" in state:
        parts.append(f"PREVIOUS ANALYSIS:\n{state['analysis']}")
    return "\n\n".join(parts) or str(state)


def _try_parse_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return None
