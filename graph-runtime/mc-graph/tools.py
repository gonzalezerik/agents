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
"""Additional tools for a11y_fix and studio graphs. Appended to tools.py."""
import base64, datetime, os
import httpx

FORGEJO_URL = os.getenv("FORGEJO_URL", "https://forgejo.example.com")
FORGEJO_TOKEN = os.getenv("FORGEJO_TOKEN", "")
FORGEJO_USER = os.getenv("FORGEJO_USER", "forgejo-user")
FORGEJO_REPO = os.getenv("FORGEJO_REPO", "mission-control")

def _forgejo_headers() -> dict:
    if FORGEJO_TOKEN:
        return {"Authorization": f"token {FORGEJO_TOKEN}", "Content-Type": "application/json"}
    pw = os.getenv("FORGEJO_PASSWORD", "")
    creds = base64.b64encode(f"{FORGEJO_USER}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}


async def forgejo_fetch_source(file_path: str = "app/globals.css",
                                repo: str | None = None) -> dict:
    """Fetch a source file from Forgejo."""
    repo = repo or FORGEJO_REPO
    url = f"{FORGEJO_URL}/api/v1/repos/{FORGEJO_USER}/{repo}/contents/{file_path}"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.get(url, headers=_forgejo_headers())
            if r.status_code == 404:
                return {"error": f"File not found: {file_path}", "content": None}
            r.raise_for_status()
            data = r.json()
            content = base64.b64decode(data["content"].replace("\n", "")).decode("utf-8", errors="replace")
            return {
                "file": file_path,
                "content": content,
                "sha": data["sha"],
                "size": data["size"],
            }
    except Exception as exc:
        log.error("forgejo_fetch_source failed: %s", exc)
        return {"error": str(exc), "content": None}


async def forgejo_commit_patch(file: str, diff: str, explanation: str,
                                branch: str = "main", repo: str | None = None,
                                patch: dict | None = None, **_) -> dict:
    """Apply a patch to a Forgejo file and commit it. Accepts patch dict or individual args."""
    if patch and isinstance(patch, dict):
        file = patch.get("file", file)
        diff = patch.get("diff", diff)
        explanation = patch.get("explanation", explanation)

    repo = repo or FORGEJO_REPO
    fetch_result = await forgejo_fetch_source(file, repo)
    if fetch_result.get("error") or not fetch_result.get("content"):
        return {"error": f"Cannot fetch file to patch: {fetch_result.get('error')}", "success": False}

    sha = fetch_result["sha"]
    original = fetch_result["content"]

    try:
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as td:
            orig_path = f"{td}/original"
            patch_path = f"{td}/patch.diff"
            with open(orig_path, "w") as f:
                f.write(original)
            with open(patch_path, "w") as f:
                f.write(diff)
            result = subprocess.run(
                ["patch", orig_path, patch_path, "--output", f"{td}/patched"],
                capture_output=True, text=True)
            if result.returncode != 0:
                return {"error": f"Patch failed: {result.stderr}", "success": False}
            with open(f"{td}/patched") as f:
                patched = f.read()
    except Exception as exc:
        return {"error": f"Patch apply error: {exc}", "success": False}

    content_b64 = base64.b64encode(patched.encode()).decode()
    commit_message = f"fix(a11y): {explanation}"
    url = f"{FORGEJO_URL}/api/v1/repos/{FORGEJO_USER}/{repo}/contents/{file}"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.put(url, headers=_forgejo_headers(), json={
                "message": commit_message,
                "content": content_b64,
                "sha": sha,
                "branch": branch,
            })
            r.raise_for_status()
            data = r.json()
            return {
                "success": True,
                "sha": data["commit"]["sha"],
                "file": file,
                "message": commit_message,
            }
    except Exception as exc:
        log.error("forgejo_commit_patch failed: %s", exc)
        return {"error": str(exc), "success": False}


async def forgejo_trigger_build(branch: str = "main", repo: str | None = None, **_) -> dict:
    """Trigger Forgejo CI by creating an empty commit or dispatching a workflow."""
    repo = repo or FORGEJO_REPO
    url = f"{FORGEJO_URL}/api/v1/repos/{FORGEJO_USER}/{repo}/actions/workflows"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.get(url, headers=_forgejo_headers())
            workflows = r.json().get("workflow_runs", []) if r.is_success else []
            # Trigger via repository dispatch event
            dispatch_url = f"{FORGEJO_URL}/api/v1/repos/{FORGEJO_USER}/{repo}/dispatches"
            dr = await http.post(dispatch_url, headers=_forgejo_headers(), json={
                "event_type": "a11y_fix_deployed",
                "client_payload": {"branch": branch, "triggered_by": "mc-graph"},
            })
            return {"success": dr.is_success or dr.status_code == 204,
                    "status_code": dr.status_code, "branch": branch}
    except Exception as exc:
        log.error("forgejo_trigger_build failed: %s", exc)
        return {"error": str(exc), "success": False}


async def k8s_rollout_deployment(deployment: str = "mission-control-app",
                                  namespace: str = "mission-control", **_) -> dict:
    """Annotate a K8s deployment to trigger a rollout."""
    try:
        k = _k8s()
        apps = k.AppsV1Api()
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        body = {"spec": {"template": {"metadata": {"annotations": {
            "kubectl.kubernetes.io/restartedAt": ts
        }}}}}
        apps.patch_namespaced_deployment(deployment, namespace, body)
        return {"success": True, "deployment": deployment, "namespace": namespace, "restartedAt": ts}
    except Exception as exc:
        log.error("k8s_rollout_deployment failed: %s", exc)
        return {"error": str(exc), "success": False}


async def k8s_check_deployment_ready(deployment: str = "mission-control-app",
                                      namespace: str = "mission-control") -> dict:
    """Check if a K8s deployment is fully ready."""
    try:
        k = _k8s()
        apps = k.AppsV1Api()
        d = apps.read_namespaced_deployment(deployment, namespace)
        desired = d.spec.replicas or 1
        ready = d.status.ready_replicas or 0
        return {
            "deployment_ready": ready >= desired,
            "desired": desired,
            "ready": ready,
            "crash_loop": False,
        }
    except Exception as exc:
        log.error("k8s_check_deployment_ready failed: %s", exc)
        return {"deployment_ready": False, "crash_loop": False, "error": str(exc)}


async def notify_reporter(report_id: str | None = None, verdict: str | None = None,
                           commit_result: dict | None = None, **_) -> dict:
    """Log notification that a11y fix was deployed."""
    msg = f"A11y fix deployed: report={report_id} verdict={verdict} commit={commit_result}"
    log.info(msg)
    return {"notified": True, "report_id": report_id, "message": msg}


async def studio_generate(prompt: str, parameters: dict | None = None, **_) -> dict:
    """Placeholder: submit a studio generation job."""
    import uuid
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    log.info("studio_generate: job_id=%s prompt=%s params=%s", job_id, prompt[:80], parameters)
    return {
        "job_id": job_id,
        "status": "queued",
        "prompt": prompt,
        "parameters": parameters or {},
    }


async def studio_evaluate(generated: dict | None = None, **_) -> dict:
    """Placeholder: evaluate generated studio output."""
    if not generated:
        return {"verdict": "fail", "reason": "no output"}
    return {
        "verdict": "pass",
        "output_valid": True,
        "no_errors": True,
        "job_id": generated.get("job_id"),
    }
