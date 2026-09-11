"""Tool implementations: K8s read/write, LLM calls."""
import logging, os
import httpx
from kubernetes import client as k8s_client, config as k8s_config

log = logging.getLogger("mc-graph.tools")
KUBECONFIG = os.getenv("KUBECONFIG", "/etc/mc-graph/kubeconfig")
MC_AGENT_URL = os.getenv("MC_AGENT_URL", "http://localhost:4001")
MC_AGENT_TOKEN = os.getenv("MC_AGENT_TOKEN", "")
_k8s_loaded = False

def _k8s():
    global _k8s_loaded
    if not _k8s_loaded:
        try:
            k8s_config.load_kube_config(KUBECONFIG)
        except Exception:
            k8s_config.load_incluster_config()
        _k8s_loaded = True
    return k8s_client

async def k8s_gather_context(pod_name: str | None = None,
                              namespace: str = "mission-control") -> dict:
    """Gather K8s context: failing pods, events, recent logs."""
    try:
        k = _k8s()
        v1 = k.CoreV1Api()
        ctx: dict = {"namespace": namespace, "pods": [], "events": []}
        pods = v1.list_namespaced_pod(namespace)
        failing = []
        for p in pods.items:
            phase = p.status.phase or "Unknown"
            restarts = sum(c.restart_count for c in (p.status.container_statuses or []))
            if phase in ("Failed","Unknown") or restarts > 3 or (pod_name and p.metadata.name == pod_name):
                pod_info = {
                    "name": p.metadata.name, "phase": phase, "restarts": restarts,
                    "conditions": [{"type": c.type, "status": c.status, "reason": c.reason}
                                   for c in (p.status.conditions or [])],
                    "containers": [],
                }
                for cs in (p.status.container_statuses or []):
                    cinfo: dict = {"name": cs.name, "ready": cs.ready, "restarts": cs.restart_count}
                    if cs.last_state and cs.last_state.terminated:
                        t = cs.last_state.terminated
                        cinfo["last_exit"] = {"reason": t.reason, "exit_code": t.exit_code}
                    pod_info["containers"].append(cinfo)
                try:
                    logs = v1.read_namespaced_pod_log(p.metadata.name, namespace, tail_lines=50)
                    pod_info["logs_tail"] = logs[-3000:]
                except Exception:
                    pod_info["logs_tail"] = ""
                failing.append(pod_info)
        events = v1.list_namespaced_event(namespace)
        recent_events = sorted(
            [{"name": e.involved_object.name, "reason": e.reason,
              "message": e.message, "type": e.type,
              "count": e.count, "last_time": str(e.last_timestamp)}
             for e in events.items if e.type == "Warning"],
            key=lambda x: x.get("last_time",""), reverse=True)[:20]
        ctx["pods"] = failing
        ctx["events"] = recent_events
        return ctx
    except Exception as exc:
        log.error("k8s_gather_context failed: %s", exc)
        return {"error": str(exc), "pods": [], "events": []}

async def k8s_restart_pod(pod_name: str, namespace: str = "mission-control") -> dict:
    try:
        k = _k8s()
        v1 = k.CoreV1Api()
        v1.delete_namespaced_pod(pod_name, namespace)
        log.info("Deleted pod %s/%s", namespace, pod_name)
        return {"deleted": pod_name, "namespace": namespace, "success": True}
    except Exception as exc:
        log.error("k8s_restart_pod failed: %s", exc)
        return {"error": str(exc), "success": False}

async def k8s_check_pod_health(pod_name: str, namespace: str = "mission-control") -> dict:
    try:
        k = _k8s()
        v1 = k.CoreV1Api()
        import time; time.sleep(5)
        base = pod_name.rsplit("-", 2)[0]
        pods = v1.list_namespaced_pod(namespace, label_selector=f"app={base}")
        for p in pods.items:
            phase = p.status.phase or "Unknown"
            restarts = sum(c.restart_count for c in (p.status.container_statuses or []))
            ready = all(c.ready for c in (p.status.container_statuses or []))
            return {"phase": phase, "restarts": restarts,
                    "ready": ready, "healthy": phase == "Running" and ready}
        return {"healthy": False, "reason": "no_pod_found"}
    except Exception as exc:
        return {"healthy": False, "error": str(exc)}

async def llm_call(system_prompt: str, user_prompt: str,
                   model: str = "auto", max_tokens: int = 2000) -> tuple[str, int, int]:
    try:
        async with httpx.AsyncClient(timeout=120) as http:
            payload = {
                "model": model if model != "auto" else "qwen3-6-35b",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "stream": False,
            }
            r = await http.post(
                f"{MC_AGENT_URL}/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {MC_AGENT_TOKEN}"},
            )
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    except Exception as exc:
        log.error("llm_call failed: %s", exc)
        return f"[LLM error: {exc}]", 0, 0
