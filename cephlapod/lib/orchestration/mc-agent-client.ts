/**
 * HTTP client for mc-agent (runs on gpuhost :4001 and llmhost-llm :4001).
 * All requests carry the shared bearer token from env.
 */

import type { HostObservedState } from "./types";

const AGENT_TOKEN = process.env.MC_AGENT_TOKEN ?? "";

const HOSTS: Record<string, string> = {
  gpuhost:    process.env.MC_AGENT_GPUHOST_URL ?? "http://localhost:4001",
  "llmhost-llm": process.env.MC_AGENT_LLMHOST_URL  ?? "http://localhost:4001",
};

function headers() {
  return { Authorization: `Bearer ${AGENT_TOKEN}`, "Content-Type": "application/json" };
}

async function get<T>(host_id: string, path: string): Promise<T> {
  const base = HOSTS[host_id];
  if (!base) throw new Error(`Unknown host: ${host_id}`);
  const res = await fetch(`${base}${path}`, {
    headers: headers(),
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) throw new Error(`mc-agent ${host_id} ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(host_id: string, path: string, body: unknown): Promise<T> {
  const base = HOSTS[host_id];
  if (!base) throw new Error(`Unknown host: ${host_id}`);
  const res = await fetch(`${base}${path}`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`mc-agent ${host_id} ${path} → ${res.status}: ${txt}`);
  }
  return res.json() as Promise<T>;
}

// ── Observed state ────────────────────────────────────────────────────────────

export async function fetchObservedState(host_id: string): Promise<HostObservedState> {
  return get<HostObservedState>(host_id, "/state");
}

export async function fetchAllObservedStates(): Promise<HostObservedState[]> {
  return Promise.all(
    Object.keys(HOSTS).map(async (host_id) => {
      try {
        return await fetchObservedState(host_id);
      } catch (err) {
        return {
          host_id,
          polled_at: new Date().toISOString(),
          reachable: false,
          gpus: [],
          running_models: [],
          agent_version: null,
        } satisfies HostObservedState;
      }
    })
  );
}

// ── Model lifecycle ───────────────────────────────────────────────────────────

export async function startModel(host_id: string, model_id: string): Promise<{ pid: number }> {
  return post(host_id, "/models/start", { model_id });
}

export async function stopModel(host_id: string, model_id: string, reason: string): Promise<void> {
  await post(host_id, "/models/stop", { model_id, reason });
}

export async function healthCheck(host_id: string): Promise<{ ok: boolean; version: string }> {
  return get(host_id, "/health");
}

// ── Shim session management ───────────────────────────────────────────────────

export async function setPassthrough(host_id: string, session_id: string, enabled: boolean): Promise<void> {
  await post(host_id, "/shim/passthrough", { session_id, enabled });
}
