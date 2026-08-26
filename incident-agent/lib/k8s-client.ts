/**
 * Minimal in-cluster Kubernetes API client using the pod's own
 * ServiceAccount token (mission-control-agent - defined 2026-07-29,
 * unused until this pod actually started running in-cluster on
 * 2026-08-25). No kubernetes client library needed for read-only list
 * calls - just the projected token + the cluster CA.
 *
 * Requires NODE_EXTRA_CA_CERTS to point at the projected CA (set in the
 * Deployment env) so plain fetch() trusts the in-cluster API server.
 */
import fs from "fs";

const K8S_API = "https://kubernetes.default.svc.cluster.local";
const TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token";

function readToken(): string | null {
  try {
    return fs.readFileSync(TOKEN_PATH, "utf8").trim();
  } catch {
    return null;
  }
}

export async function k8sGet<T = unknown>(apiPath: string): Promise<T | null> {
  const token = readToken();
  if (!token) return null;
  try {
    const res = await fetch(`${K8S_API}${apiPath}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/** DELETE a specific pod - the proven-safe "restart" pattern in this cluster
 *  (see wiki gotchas: ArgoCD selfHeal reverts a `rollout restart`/template
 *  patch within minutes, but deleting a pod directly is fine - the
 *  ReplicaSet/Deployment recreates it with the current spec). Requires the
 *  `delete` verb on pods, added to mission-control-agent's RBAC alongside
 *  this feature. */
export async function k8sDeletePod(namespace: string, podName: string): Promise<{ ok: boolean; status: number }> {
  const token = readToken();
  if (!token) return { ok: false, status: 0 };
  try {
    const res = await fetch(`${K8S_API}/api/v1/namespaces/${namespace}/pods/${podName}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(10000),
    });
    return { ok: res.ok, status: res.status };
  } catch {
    return { ok: false, status: 0 };
  }
}

export interface PodSummary {
  name: string;
  namespace: string;
  phase: string;
  ready: boolean;
  restartCount: number;
  reason: string | null;
}

interface PodListResponse {
  items?: Array<{
    metadata: { name: string; namespace: string };
    status?: {
      phase?: string;
      containerStatuses?: Array<{ ready: boolean; restartCount: number; state?: Record<string, { reason?: string }> }>;
    };
  }>;
}

/** List pods in a namespace, optionally filtered by label selector (e.g. "app=mission-control"). */
export async function listPods(namespace: string, labelSelector?: string): Promise<PodSummary[] | null> {
  const query = labelSelector ? `?labelSelector=${encodeURIComponent(labelSelector)}` : "";
  const data = await k8sGet<PodListResponse>(`/api/v1/namespaces/${namespace}/pods${query}`);
  if (!data?.items) return null;
  return data.items.map((p) => {
    const cs = p.status?.containerStatuses?.[0];
    const notReadyReason = cs?.state ? Object.values(cs.state)[0]?.reason ?? null : null;
    return {
      name: p.metadata.name,
      namespace: p.metadata.namespace,
      phase: p.status?.phase ?? "Unknown",
      ready: cs?.ready ?? false,
      restartCount: cs?.restartCount ?? 0,
      reason: notReadyReason,
    };
  });
}

export interface K8sEvent {
  reason: string;
  message: string;
  count: number;
  lastTimestamp: string;
  involvedObject: string;
}

interface EventListResponse {
  items?: Array<{
    reason?: string;
    message?: string;
    count?: number;
    lastTimestamp?: string;
    involvedObject?: { kind?: string; name?: string };
  }>;
}

/** Recent events in a namespace - what actually happened, not just current status. */
export async function listRecentEvents(namespace: string, limit = 10): Promise<K8sEvent[] | null> {
  const data = await k8sGet<EventListResponse>(`/api/v1/namespaces/${namespace}/events`);
  if (!data?.items) return null;
  return data.items
    .sort((a, b) => (b.lastTimestamp ?? "").localeCompare(a.lastTimestamp ?? ""))
    .slice(0, limit)
    .map((e) => ({
      reason: e.reason ?? "",
      message: e.message ?? "",
      count: e.count ?? 1,
      lastTimestamp: e.lastTimestamp ?? "",
      involvedObject: `${e.involvedObject?.kind ?? "?"}/${e.involvedObject?.name ?? "?"}`,
    }));
}

export interface ArgoApplicationSummary {
  name: string;
  namespace: string;
  syncStatus: string;
  healthStatus: string;
  repoPath: string | null;
}

interface ArgoApplicationListResponse {
  items?: Array<{
    metadata: { name: string; namespace: string };
    spec?: { source?: { path?: string } };
    status?: {
      sync?: { status?: string };
      health?: { status?: string };
    };
  }>;
}

/** List every ArgoCD Application in the cluster - the auto-discovery source of truth. */
export async function listArgoApplications(): Promise<ArgoApplicationSummary[] | null> {
  const data = await k8sGet<ArgoApplicationListResponse>("/apis/argoproj.io/v1alpha1/applications");
  if (!data?.items) return null;
  return data.items.map((item) => ({
    name: item.metadata.name,
    namespace: item.metadata.namespace,
    syncStatus: item.status?.sync?.status ?? "Unknown",
    healthStatus: item.status?.health?.status ?? "Unknown",
    repoPath: item.spec?.source?.path ?? null,
  }));
}
