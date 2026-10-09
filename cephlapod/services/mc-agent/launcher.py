"""
Start / stop llama-server processes based on model registry placement data.
Tracks pid → model_id in memory; process table is rebuilt on restart.
"""
import os, subprocess, signal, time, shlex
from typing import Any
from models import get_model
from config import HOST_ID


# pid → {model_id, port, started_at}
_running: dict[int, dict[str, Any]] = {}
_next_port = 8010  # base port for dynamically launched models


def _alloc_port() -> int:
    global _next_port
    used = {v["port"] for v in _running.values()}
    while _next_port in used:
        _next_port += 1
    p = _next_port
    _next_port += 1
    return p


def managed_pids() -> dict[int, str]:
    """Return {pid: model_id} for all tracked processes."""
    return {pid: info["model_id"] for pid, info in _running.items()}


def start(model_id: str) -> int:
    """Launch the model. Returns PID."""
    model = get_model(model_id)
    if model is None:
        raise ValueError(f"Model {model_id!r} not found in registry")

    placement = model["placement"]
    if placement["host_id"] != HOST_ID:
        raise ValueError(f"Model {model_id!r} belongs to {placement['host_id']!r}, not {HOST_ID!r}")

    binary   = placement["llama_binary"]
    raw_args = placement["launch_args"]
    port     = _alloc_port()

    if not binary or not os.path.isfile(binary):
        raise FileNotFoundError(f"llama-server binary not found: {binary!r}")

    # Inject port and model path
    weights  = model["weights_path"]
    cmd = [binary, "--model", weights] + shlex.split(raw_args) + ["--port", str(port)]

    # GPU environment: set CUDA_VISIBLE_DEVICES from placement.gpus (UUIDs)
    env = os.environ.copy()
    gpus = placement.get("gpus", [])
    if gpus:
        env["CUDA_VISIBLE_DEVICES"] = ",".join(gpus)
    else:
        env["CUDA_VISIBLE_DEVICES"] = ""  # CPU-only

    proc = subprocess.Popen(
        cmd, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _running[proc.pid] = {
        "model_id": model_id,
        "port": port,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return proc.pid


def stop(model_id: str, reason: str = "") -> bool:
    """SIGTERM the process running model_id. Returns True if found."""
    for pid, info in list(_running.items()):
        if info["model_id"] == model_id:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            del _running[pid]
            return True
    return False


def running_ports() -> dict[str, int]:
    """Return {model_id: port} for all tracked live processes."""
    result = {}
    for pid, info in list(_running.items()):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            del _running[pid]
            continue
        result[info["model_id"]] = info["port"]
    return result


def running_models() -> list[dict[str, Any]]:
    """Return list of running model state dicts for /state endpoint."""
    result = []
    for pid, info in list(_running.items()):
        # Check if process is still alive
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            del _running[pid]
            continue

        model = get_model(info["model_id"])
        result.append({
            "model_id": info["model_id"],
            "pid": pid,
            "gpus": model["placement"]["gpus"] if model else [],
            "health": "healthy",   # mc-agent can probe /health on the port for accuracy
            "tokens_sec": None,
            "queue_depth": None,
            "started_at": info["started_at"],
        })
    return result
