"""GPU state via nvidia-smi (subprocess, not pynvml — no lib dep)."""
import subprocess, json, re
from typing import Any


def _smi(*fields: str) -> list[dict[str, str]]:
    query = ",".join(fields)
    out = subprocess.check_output(
        ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
        text=True,
    )
    rows = []
    for line in out.strip().splitlines():
        vals = [v.strip() for v in line.split(",")]
        rows.append(dict(zip(fields, vals)))
    return rows


def _pmon() -> list[dict[str, Any]]:
    """nvidia-smi pmon for per-process VRAM."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "pmon", "-c", "1", "-s", "m"],
            text=True,
        )
    except subprocess.CalledProcessError:
        return []
    procs: list[dict[str, Any]] = []
    for line in out.strip().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            procs.append({
                "gpu_idx": int(parts[0]),
                "pid": int(parts[1]),
                "fb_mib": int(parts[3]) if parts[3] != "-" else 0,
            })
        except ValueError:
            continue
    return procs


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline") as f:
            return f.read().replace("\x00", " ").strip()[:200]
    except OSError:
        return ""


def gpu_state(managed_pids: dict[int, str]) -> list[dict[str, Any]]:
    """
    Returns list of GPU state dicts.
    managed_pids: {pid: model_id} for dashboard-launched processes.
    """
    gpus = _smi(
        "uuid", "name", "index",
        "memory.total", "memory.used",
        "utilization.gpu", "temperature.gpu",
    )
    proc_rows = _pmon()

    # Build uuid → index map
    uuid_to_idx = {g["uuid"]: int(g["index"]) for g in gpus}

    result = []
    for g in gpus:
        idx = int(g["index"])
        procs_on_gpu = [p for p in proc_rows if p["gpu_idx"] == idx]
        proc_list = []
        for p in procs_on_gpu:
            pid = p["pid"]
            model_id = managed_pids.get(pid)
            proc_list.append({
                "pid": pid,
                "model_id": model_id,
                "vram_mib": p["fb_mib"],
                "is_foreign": model_id is None,
                "command": _cmdline(pid) if model_id is None else "",
            })

        result.append({
            "uuid": g["uuid"],
            "name": g["name"],
            "index": idx,
            "vram_total_mib": int(g["memory.total"]),
            "vram_used_mib": int(g["memory.used"]),
            "util_pct": int(g["utilization.gpu"]),
            "temp_c": int(g["temperature.gpu"]),
            "processes": proc_list,
        })
    return result
